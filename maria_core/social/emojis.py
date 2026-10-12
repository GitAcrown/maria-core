"""Emojis du serveur : appris dans les réactions et dans le texte, choisis selon le message."""

import math
import re
from collections.abc import Callable
from datetime import datetime

from maria_core.db import Database

DEFAULT_POOL = ("👍", "😂", "🔥", "👀", "❤️", "😮")
_CUSTOM = re.compile(r"<a?:\w+:\d+>")
_UNICODE = re.compile(
    "[\U0001f1e6-\U0001f1ff]{2}|[\U0001f300-\U0001faff☀-➿][️\U0001f3fb-\U0001f3ff]?"
)
_WORD = re.compile(r"[a-zàâäéèêëïîôùûüçœæ]{4,}", re.IGNORECASE)
_SHORTLIST = 5

type Usable = Callable[[str], bool]


def emojis_in(text: str) -> list[str]:
    found = _CUSTOM.findall(text or "")
    found.extend(_UNICODE.findall(_CUSTOM.sub(" ", text or "")))
    return list(dict.fromkeys(found))


def words_of(text: str) -> list[str]:
    cleaned = _UNICODE.sub(" ", _CUSTOM.sub(" ", text or ""))
    return list(dict.fromkeys(word.casefold() for word in _WORD.findall(cleaned)))[:12]


def learn(database: Database, guild_id: int, emoji: str, context: str, now: datetime) -> None:
    database.execute(
        """
        INSERT INTO emoji_usage (guild_id, emoji, uses, updated_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(guild_id, emoji) DO UPDATE SET
            uses = uses + 1,
            updated_at = excluded.updated_at
        """,
        (guild_id, emoji, now.isoformat()),
    )
    for word in words_of(context):
        database.execute(
            """
            INSERT INTO emoji_words (guild_id, emoji, word, hits) VALUES (?, ?, ?, 1)
            ON CONFLICT(guild_id, emoji, word) DO UPDATE SET hits = hits + 1
            """,
            (guild_id, emoji, word),
        )


def learn_text(database: Database, guild_id: int, text: str, now: datetime, usable: Usable) -> int:
    """Chaque emoji écrit dans un message est appris avec les mots qui l'entourent."""
    learned = 0
    for emoji in emojis_in(text):
        if usable(emoji):
            learn(database, guild_id, emoji, text, now)
            learned += 1
    return learned


def shortlist(database: Database, guild_id: int, text: str, usable: Usable) -> tuple[str, ...]:
    """Les emojis appris les plus proches du message, sinon une base sobre."""
    rows = database.fetchall(
        "SELECT emoji, uses FROM emoji_usage WHERE guild_id = ? ORDER BY uses DESC LIMIT 40",
        (guild_id,),
    )
    words = words_of(text)
    scored: list[tuple[float, str]] = []
    for row in rows:
        emoji = str(row["emoji"])
        if not usable(emoji):
            continue
        overlap = _overlap(database, guild_id, emoji, words)
        scored.append((math.log1p(int(row["uses"])) + 2.0 * overlap, emoji))
    scored.sort(key=lambda item: (-item[0], item[1]))
    picked = [emoji for _score, emoji in scored[:_SHORTLIST]]
    for emoji in DEFAULT_POOL:
        if len(picked) >= _SHORTLIST:
            break
        if emoji not in picked:
            picked.append(emoji)
    return tuple(picked)


def _overlap(database: Database, guild_id: int, emoji: str, words: list[str]) -> float:
    if not words:
        return 0.0
    marks = ", ".join("?" for _ in words)
    row = database.fetchone(
        f"""
        SELECT COALESCE(SUM(hits), 0) AS n FROM emoji_words
        WHERE guild_id = ? AND emoji = ? AND word IN ({marks})
        """,
        (guild_id, emoji, *words),
    )
    return math.log1p(int(row["n"])) if row is not None else 0.0
