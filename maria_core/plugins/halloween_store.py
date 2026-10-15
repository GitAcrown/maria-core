"""Halloween 2026 : sac, collection de bonbons et gages en cours (SQLite).

Fichier de l'événement : il part avec le plugin (voir RETRAIT_HALLOWEEN.md).
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from maria_core.db import Database
from maria_core.plugins.halloween_sweets import (
    SWEETS,
    Sweet,
    draw_sweet,
    draw_trick,
    respects,
)

RINGS_PER_DAY = 4
RING_GAP = timedelta(hours=3)
DARE_MESSAGES = 3
DARE_WINDOW = timedelta(hours=1)
TRICK_CHANCE = 0.35
RANKING_SIZE = 10

_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS halloween_bag (
        guild_id INTEGER NOT NULL,
        user_id  INTEGER NOT NULL,
        name     TEXT NOT NULL DEFAULT '',
        candies  INTEGER NOT NULL DEFAULT 0,
        tricks   INTEGER NOT NULL DEFAULT 0,
        day      TEXT NOT NULL DEFAULT '',
        rings    INTEGER NOT NULL DEFAULT 0,
        last_at  TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (guild_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS halloween_sweets (
        guild_id INTEGER NOT NULL,
        user_id  INTEGER NOT NULL,
        kind     TEXT NOT NULL,
        count    INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, kind)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS halloween_dare (
        guild_id   INTEGER NOT NULL,
        user_id    INTEGER NOT NULL,
        kind       TEXT NOT NULL,
        word       TEXT NOT NULL DEFAULT '',
        text       TEXT NOT NULL,
        left       INTEGER NOT NULL,
        expires_at TEXT NOT NULL,
        after_id   INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    )
    """,
)
_BAG = "SELECT * FROM halloween_bag WHERE guild_id = ? AND user_id = ?"


@dataclass(frozen=True, slots=True)
class Player:
    """Un sac par serveur et par personne (`guild` vaut 0 en message privé)."""

    guild: int
    user: int
    name: str
    message: int = 0  # le message qui a sonné : un gage ne compte que ce qui vient après


def ensure_table(database: Database) -> None:
    """Crée les tables, et ajoute `last_at` à un sac d'avant la pause de 3 h."""
    for statement in _TABLES:
        database.execute(statement)
    columns = {str(row["name"]) for row in database.fetchall("PRAGMA table_info(halloween_bag)")}
    if "last_at" not in columns:
        database.execute("ALTER TABLE halloween_bag ADD COLUMN last_at TEXT NOT NULL DEFAULT ''")


def active_dares(database: Database) -> set[tuple[int, int]]:
    rows = database.fetchall("SELECT guild_id, user_id FROM halloween_dare")
    return {(int(row["guild_id"]), int(row["user_id"])) for row in rows}


def ring(database: Database, who: Player, now: datetime, dice: random.Random) -> dict[str, Any]:
    today = now.date().isoformat()
    with database.transaction():
        _open_bag(database, who)
        row = database.fetchone(_BAG, (who.guild, who.user))
        assert row is not None
        used = int(row["rings"]) if row["day"] == today else 0
        if used >= RINGS_PER_DAY:
            return _closed(row, "day", 0, 0)
        waiting = _next_ring(row["last_at"], now)
        if waiting:
            return _closed(row, "wait", waiting, RINGS_PER_DAY - used)
        data = _draw(database, who, now, dice)
        database.execute(
            "UPDATE halloween_bag SET name = ?, tricks = tricks + ?, day = ?, rings = ?, "
            "last_at = ? WHERE guild_id = ? AND user_id = ?",
            (
                who.name,
                int(data["outcome"] == "trick"),
                today,
                used + 1,
                now.isoformat(),
                who.guild,
                who.user,
            ),
        )
        bag = database.fetchone(_BAG, (who.guild, who.user))
    data["candies"] = int(bag["candies"]) if bag is not None else 0
    data["sweets"] = _collection(database, who)
    data["rings_left"] = RINGS_PER_DAY - used - 1
    data["next_at"] = int((now + RING_GAP).timestamp()) if used + 1 < RINGS_PER_DAY else 0
    return data


def _draw(database: Database, who: Player, now: datetime, dice: random.Random) -> dict[str, Any]:
    base: dict[str, Any] = {"action": "ring", "gained": 0, "stolen": 0, "dare": None}
    if dice.random() < TRICK_CHANCE:
        trick = draw_trick(dice)
        base.update(outcome="trick", gift=trick.text)
        if trick.steal:
            base["stolen"] = _steal(database, who, trick.steal, dice)
        if trick.is_dare:
            base["dare"] = _set_dare(database, who, now, trick.kind, trick.word, trick.text)
        return base
    sweet = draw_sweet(dice)
    _give(database, who, sweet, sweet.pieces)
    base.update(outcome="treat", gift=sweet.gift, gained=sweet.pieces, emoji=sweet.emoji)
    return base


def bag(database: Database, who: Player, now: datetime) -> dict[str, Any]:
    row = database.fetchone(_BAG, (who.guild, who.user))
    dare = _dare_of(database, who)
    if row is None:
        return {"action": "bag", "candies": 0, "tricks": 0, "rings_left": RINGS_PER_DAY} | {
            "sweets": _collection(database, who),
            "dare": dare,
        }
    used = int(row["rings"]) if row["day"] == now.date().isoformat() else 0
    left = max(0, RINGS_PER_DAY - used)
    return {
        "action": "bag",
        "candies": int(row["candies"]),
        "tricks": int(row["tricks"]),
        "rings_left": left,
        "next_at": _next_ring(row["last_at"], now) if left else 0,
        "sweets": _collection(database, who),
        "dare": dare,
    }


def ranking(database: Database, who: Player) -> dict[str, Any]:
    rows = database.fetchall(
        "SELECT user_id, name, candies FROM halloween_bag WHERE guild_id = ? AND "
        "(candies > 0 OR tricks > 0) ORDER BY candies DESC, tricks DESC, name LIMIT ?",
        (who.guild, RANKING_SIZE),
    )
    board = [
        {
            "name": str(row["name"] or "Quelqu'un"),
            "candies": int(row["candies"]),
            "me": row["user_id"] == who.user,
        }
        for row in rows
    ]
    return {"action": "ranking", "board": board}


def judge(
    database: Database,
    who: Player,
    text: str,
    message_id: int,
    now: datetime,
    dice: random.Random,
) -> tuple[Sweet | None, bool]:
    """Un message de plus pour quelqu'un qui a un gage : (bonbon gagné, gage terminé)."""
    with database.transaction():
        row = database.fetchone(
            "SELECT * FROM halloween_dare WHERE guild_id = ? AND user_id = ?", (who.guild, who.user)
        )
        if row is None:
            return None, True
        if datetime.fromisoformat(str(row["expires_at"])) < now:
            _drop_dare(database, who)
            return None, True
        if message_id <= int(row["after_id"]):
            return None, False
        if respects(str(row["kind"]), str(row["word"]), text):
            _drop_dare(database, who)
            sweet = draw_sweet(dice)
            _give(database, who, sweet, 1)
            return sweet, True
        left = int(row["left"]) - 1
        if left <= 0:
            _drop_dare(database, who)
            return None, True
        database.execute(
            "UPDATE halloween_dare SET left = ? WHERE guild_id = ? AND user_id = ?",
            (left, who.guild, who.user),
        )
        return None, False


def _closed(row: Any, reason: str, next_at: int, left: int) -> dict[str, Any]:
    return {
        "action": "ring",
        "outcome": "closed",
        "reason": reason,
        "candies": int(row["candies"]),
        "tricks": int(row["tricks"]),
        "rings_left": left,
        "next_at": next_at,
    }


def _next_ring(last_at: object, now: datetime) -> int:
    """Quand la porte rouvre (timestamp), ou 0 si la pause de 3 h est passée."""
    try:
        last = datetime.fromisoformat(str(last_at))
    except ValueError:
        return 0
    reopen = last + RING_GAP
    return int(reopen.timestamp()) if reopen > now else 0


def _open_bag(database: Database, who: Player) -> None:
    database.execute(
        "INSERT INTO halloween_bag (guild_id, user_id, name) VALUES (?, ?, ?) "
        "ON CONFLICT (guild_id, user_id) DO NOTHING",
        (who.guild, who.user, who.name),
    )


def _counts(database: Database, who: Player) -> dict[str, int]:
    rows = database.fetchall(
        "SELECT kind, count FROM halloween_sweets WHERE guild_id = ? AND user_id = ?",
        (who.guild, who.user),
    )
    return {str(row["kind"]): int(row["count"]) for row in rows}


def _collection(database: Database, who: Player) -> list[tuple[str, int]]:
    """Les cinq bonbons dans l'ordre, avec leur nombre (un ancien sac : des bonbons simples)."""
    counts = _counts(database, who)
    row = database.fetchone(_BAG, (who.guild, who.user))
    total = int(row["candies"]) if row is not None else 0
    counts["candy"] = counts.get("candy", 0) + max(0, total - sum(counts.values()))
    return [(sweet.emoji, counts.get(sweet.key, 0)) for sweet in SWEETS]


def _normalize(database: Database, who: Player) -> None:
    """Range dans « bonbon » les pièces d'un sac d'avant la collection."""
    row = database.fetchone(_BAG, (who.guild, who.user))
    total = int(row["candies"]) if row is not None else 0
    extra = total - sum(_counts(database, who).values())
    if extra > 0:
        _add(database, who, "candy", extra)


def _add(database: Database, who: Player, kind: str, pieces: int) -> None:
    database.execute(
        "INSERT INTO halloween_sweets (guild_id, user_id, kind, count) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (guild_id, user_id, kind) DO UPDATE SET count = count + excluded.count",
        (who.guild, who.user, kind, pieces),
    )


def _give(database: Database, who: Player, sweet: Sweet, pieces: int) -> None:
    _normalize(database, who)
    _add(database, who, sweet.key, pieces)
    database.execute(
        "UPDATE halloween_bag SET candies = candies + ? WHERE guild_id = ? AND user_id = ?",
        (pieces, who.guild, who.user),
    )


def _steal(database: Database, who: Player, amount: int, dice: random.Random) -> int:
    """Retire au hasard jusqu'à `amount` pièces de la collection, jamais plus qu'il n'y en a."""
    _normalize(database, who)
    pool = [kind for kind, count in _counts(database, who).items() for _ in range(count)]
    taken = dice.sample(pool, min(amount, len(pool)))
    for kind in taken:
        _add(database, who, kind, -1)
    database.execute(
        "UPDATE halloween_bag SET candies = candies - ? WHERE guild_id = ? AND user_id = ?",
        (len(taken), who.guild, who.user),
    )
    return len(taken)


def _set_dare(
    database: Database, who: Player, now: datetime, kind: str, word: str, text: str
) -> dict[str, Any]:
    expires = now + DARE_WINDOW
    database.execute(
        "INSERT OR REPLACE INTO halloween_dare "
        "(guild_id, user_id, kind, word, text, left, expires_at, after_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (who.guild, who.user, kind, word, text, DARE_MESSAGES, expires.isoformat(), who.message),
    )
    return {"text": text, "expires_at": int(expires.timestamp())}


def _dare_of(database: Database, who: Player) -> dict[str, Any] | None:
    row = database.fetchone(
        "SELECT text, expires_at FROM halloween_dare WHERE guild_id = ? AND user_id = ?",
        (who.guild, who.user),
    )
    if row is None:
        return None
    expires = datetime.fromisoformat(str(row["expires_at"]))
    return {"text": str(row["text"]), "expires_at": int(expires.timestamp())}


def _drop_dare(database: Database, who: Player) -> None:
    database.execute(
        "DELETE FROM halloween_dare WHERE guild_id = ? AND user_id = ?", (who.guild, who.user)
    )
