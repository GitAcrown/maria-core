"""Halloween 2026 : « bonbons ou sort », un outil qui n'existe que du 15 octobre au 1er novembre.

Pour retirer l'événement : suivre RETRAIT_HALLOWEEN.md (à la racine du projet). L'outil
s'éteint de lui-même après le 1er novembre ; la table `halloween_bag` peut rester ou être
supprimée (DROP TABLE).
"""

import asyncio
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.db import Database
from maria_core.ledger import note_undo
from maria_core.plugins import PluginHost
from maria_core.ui.emojis import FALLBACKS
from maria_core.ui.widgets import Rendered, card, footer, heading, separator, text

NAME = "halloween"
FIRST_DAY = date(2026, 10, 15)
LAST_DAY = date(2026, 11, 1)
RINGS_PER_DAY = 4
RING_GAP = timedelta(hours=3)
_PARIS = ZoneInfo("Europe/Paris")
_TRICK_CHANCE = 0.35
_RANKING_SIZE = 10
CANDY = "<:candy:1560363012874043422>"
PUMPKIN = "<:pumpkin:1560363014048448594>"
GOBLET = "<:goblet:1560364573905780827>"
_FALLBACKS = {CANDY: "🍬", PUMPKIN: "🎃", GOBLET: "🏆"}

# (ce que MARIA donne, nombre de bonbons, poids du tirage)
_TREATS = (
    ("un bonbon", 1, 40),
    ("deux caramels", 2, 25),
    ("une sucette citrouille", 2, 15),
    ("un chocolat en forme de fantôme", 3, 8),
    ("une sucette en or", 5, 2),
)
# (le sort, bonbons volés)
_TRICKS = (
    ("Parle comme un vieux pirate dans ton prochain message.", 0),
    ("Place le mot « citrouille » dans tes trois prochains messages.", 0),
    ("Raconte ta plus grosse frayeur en une phrase.", 0),
    ("Fais un compliment bien macabre à la prochaine personne qui parle.", 0),
    ("Écris ton prochain message sans aucune voyelle « e ».", 0),
    ("Une sorcière te chipe deux bonbons dans ton sac !", 2),
    ("Un fantôme farceur te prend un bonbon !", 1),
)

type Clock = Callable[[], datetime]


def _now(clock: Clock | None) -> datetime:
    return (clock() if clock is not None else datetime.now(_PARIS)).astimezone(_PARIS)


def _today(clock: Clock | None) -> date:
    return _now(clock).date()


def in_season(clock: Clock | None = None) -> bool:
    return FIRST_DAY <= _today(clock) <= LAST_DAY


def setup(app: PluginHost) -> None:
    for tag, plain in _FALLBACKS.items():
        FALLBACKS[tag] = plain  # repli Unicode si le bot ne voit pas l'emoji
        note_undo(lambda tag=tag: FALLBACKS.pop(tag, None))
    ensure_table(app.database)
    app.capabilities.register(halloween_capability(app.database))
    app.widgets.register("trick_or_treat", render_halloween)


_TABLE = """
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
"""


def ensure_table(database: Database) -> None:
    """Crée la table, et y ajoute `last_at` si elle date d'avant la pause de 3 h."""
    database.execute(_TABLE)
    columns = {str(row["name"]) for row in database.fetchall("PRAGMA table_info(halloween_bag)")}
    if "last_at" not in columns:
        database.execute("ALTER TABLE halloween_bag ADD COLUMN last_at TEXT NOT NULL DEFAULT ''")


@dataclass(frozen=True, slots=True)
class Player:
    """Un sac par serveur et par personne (`guild` vaut 0 en message privé)."""

    guild: int
    user: int
    name: str


async def play(
    database: Database,
    who: Player,
    action: str,
    *,
    clock: Clock | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """`ring`, `bag` ou `ranking` : utilisé par l'outil du modèle et par le menu /halloween."""
    now = _now(clock)
    if action == "ranking":
        return await asyncio.to_thread(_ranking, database, who)
    if action == "bag":
        return await asyncio.to_thread(_bag, database, who, now)
    return await asyncio.to_thread(_ring, database, who, now, rng or random.SystemRandom())


def halloween_capability(
    database: Database,
    *,
    clock: Clock | None = None,
    rng: random.Random | None = None,
) -> Capability:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        who = Player(context.guild_id or 0, context.user_id, context.author_name)
        data = await play(database, who, str(args.get("action") or "ring"), clock=clock, rng=rng)
        return Result(ok=True, data=data, widget="trick_or_treat")

    return Capability(
        name="trick_or_treat",
        description=(
            "Halloween, bonbons ou sort. action=ring quand quelqu'un sonne à ta porte : « bonbons "
            "ou un sort », « trick or treat », « toc toc », « ding dong », « on frappe à ta "
            "porte », ou il veut des bonbons (le tirage est fait par l'outil, jamais par "
            "toi ; une sonnerie toutes les 3 h et 4 par jour au plus, par personne) ; "
            "action=bag pour voir son sac de bonbons ; action=ranking pour le classement du "
            "serveur. Joue le jeu avec une touche macabre, brièvement : la carte affiche déjà "
            "le résultat."
        ),
        parameters={
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["ring", "bag", "ranking"]}},
            "required": ["action"],
        },
        risk=Risk.WRITE,
        run=run,
        active=lambda: in_season(clock),
    )


def _ring(database: Database, who: Player, now: datetime, dice: random.Random) -> dict[str, Any]:
    today = now.date().isoformat()
    with database.transaction():
        _open_bag(database, who)
        row = database.fetchone(_BAG, (who.guild, who.user))
        rings = int(row["rings"]) if row is not None and row["day"] == today else 0
        candies = int(row["candies"]) if row is not None else 0
        tricks = int(row["tricks"]) if row is not None else 0
        if rings >= RINGS_PER_DAY:
            return _closed(candies, tricks, "day", 0, 0)
        waiting = _next_ring(row["last_at"] if row is not None else "", now)
        if waiting:
            return _closed(candies, tricks, "wait", waiting, RINGS_PER_DAY - rings)
        gained, stolen, outcome, gift = _draw(dice, candies)
        candies += gained - stolen
        tricks += outcome == "trick"
        database.execute(
            "UPDATE halloween_bag SET name = ?, candies = ?, tricks = ?, day = ?, rings = ?, "
            "last_at = ? WHERE guild_id = ? AND user_id = ?",
            (who.name, candies, tricks, today, rings + 1, now.isoformat(), who.guild, who.user),
        )
    return {
        "action": "ring",
        "outcome": outcome,
        "gift": gift,
        "gained": gained,
        "stolen": stolen,
        "candies": candies,
        "rings_left": RINGS_PER_DAY - rings - 1,
        "next_at": int((now + RING_GAP).timestamp()) if rings + 1 < RINGS_PER_DAY else 0,
    }


def _draw(dice: random.Random, candies: int) -> tuple[int, int, str, str]:
    """Bonbons gagnés, bonbons volés, `treat` ou `trick`, et le texte du cadeau ou du sort."""
    if dice.random() < _TRICK_CHANCE:
        trick, steal = dice.choice(_TRICKS)
        return 0, min(steal, candies), "trick", trick
    weights = [weight for _gift, _worth, weight in _TREATS]
    gift, worth, _weight = dice.choices(_TREATS, weights=weights)[0]
    return worth, 0, "treat", gift


def _next_ring(last_at: object, now: datetime) -> int:
    """Quand la porte rouvre (timestamp), ou 0 si la pause de 3 h est passée."""
    try:
        last = datetime.fromisoformat(str(last_at))
    except ValueError:
        return 0
    reopen = last + RING_GAP
    return int(reopen.timestamp()) if reopen > now else 0


def _closed(candies: int, tricks: int, reason: str, next_at: int, left: int) -> dict[str, Any]:
    return {
        "action": "ring",
        "outcome": "closed",
        "reason": reason,
        "candies": candies,
        "tricks": tricks,
        "rings_left": left,
        "next_at": next_at,
    }


def _open_bag(database: Database, who: Player) -> None:
    database.execute(
        "INSERT INTO halloween_bag (guild_id, user_id, name) VALUES (?, ?, ?) "
        "ON CONFLICT (guild_id, user_id) DO NOTHING",
        (who.guild, who.user, who.name),
    )


_BAG = "SELECT * FROM halloween_bag WHERE guild_id = ? AND user_id = ?"


def _bag(database: Database, who: Player, now: datetime) -> dict[str, Any]:
    row = database.fetchone(_BAG, (who.guild, who.user))
    if row is None:
        return {"action": "bag", "candies": 0, "tricks": 0, "rings_left": RINGS_PER_DAY}
    used = int(row["rings"]) if row["day"] == now.date().isoformat() else 0
    left = max(0, RINGS_PER_DAY - used)
    return {
        "action": "bag",
        "candies": int(row["candies"]),
        "tricks": int(row["tricks"]),
        "rings_left": left,
        "next_at": _next_ring(row["last_at"], now) if left else 0,
    }


def _ranking(database: Database, who: Player) -> dict[str, Any]:
    rows = database.fetchall(
        "SELECT user_id, name, candies FROM halloween_bag WHERE guild_id = ? AND "
        "(candies > 0 OR tricks > 0) ORDER BY candies DESC, tricks DESC, name LIMIT ?",
        (who.guild, _RANKING_SIZE),
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


def render_halloween(data: Mapping[str, Any]) -> Rendered:
    title = heading("Bonbons ou sort", emoji=PUMPKIN)
    built = card(title, separator(wide=True), text(result_text(data)), footer(status_text(data)))
    if data.get("action") == "ranking":
        return Rendered(cards=(built,))
    note = f"trick_or_treat : {data.get('outcome', '')}, {data.get('candies', 0)} bonbons au total"
    return Rendered(cards=(built,), note=note if data.get("action") == "ring" else "")


def result_text(data: Mapping[str, Any]) -> str:
    """Ce qui s'est passé : sonnerie, contenu du sac ou classement."""
    action = data.get("action")
    if action == "ranking":
        return _board_text(data.get("board") or [])
    if action == "bag":
        return (
            f"**{data.get('candies', 0)}** {CANDY} dans ton sac"
            f" · {data.get('tricks', 0)} sort(s) subi(s)"
        )
    outcome = data.get("outcome")
    if outcome == "closed":
        if data.get("reason") == "wait" and data.get("next_at"):
            return f"La porte reste fermée… Reviens <t:{data['next_at']}:R>."
        return "La porte reste fermée… Reviens demain pour de nouvelles sonneries."
    if outcome == "trick":
        lost = int(data.get("stolen") or 0)
        extra = f" (-{lost} {CANDY})" if lost else ""
        return f"**Un sort !** {data.get('gift')}{extra}"
    return f"**Des bonbons !** Tu reçois {data.get('gift')} (+{data.get('gained')} {CANDY})"


def status_text(data: Mapping[str, Any]) -> str:
    """Pied de carte : le sac et les sonneries qui restent."""
    if data.get("action") == "ranking":
        return "Classement du serveur"
    left = _rings_text(int(data.get("rings_left") or 0))
    if data.get("next_at") and data.get("rings_left") != 0:
        left += f"  ·  prochaine <t:{data['next_at']}:R>"
    if data.get("action") == "bag":
        return left
    return f"Sac · {data.get('candies', 0)} {CANDY}  ·  {left}"


def _rings_text(left: int) -> str:
    if left <= 0:
        return "plus de sonnerie aujourd'hui"
    return f"{left} sonnerie{'s' if left > 1 else ''} restante{'s' if left > 1 else ''} aujourd'hui"


def _board_text(board: list[Mapping[str, Any]]) -> str:
    if not board:
        return "Personne n'a encore sonné ici. Qui ose frapper à la porte ?"
    medals = ("🥇", "🥈", "🥉")
    lines = []
    for rank, entry in enumerate(board):
        mark = medals[rank] if rank < len(medals) else f"{rank + 1}."
        name = f"**{entry['name']}**" if entry.get("me") else str(entry["name"])
        lines.append(f"{mark} {name} · {entry['candies']} {CANDY}")
    return "\n".join(lines)
