"""Halloween 2026 : « bonbons ou sort », un outil qui n'existe que du 15 octobre au 1er novembre.

Pour retirer l'événement : suivre RETRAIT_HALLOWEEN.md (à la racine du projet). L'outil
s'éteint de lui-même après le 1er novembre ; la table `halloween_bag` peut rester ou être
supprimée (DROP TABLE).
"""

import asyncio
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
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
RINGS_PER_DAY = 3
_PARIS = ZoneInfo("Europe/Paris")
_TRICK_CHANCE = 0.35
_RANKING_SIZE = 10
_CANDY = "<:candy:1560363012874043422>"
_PUMPKIN = "<:pumpkin:1560363014048448594>"
_FALLBACKS = {_CANDY: "🍬", _PUMPKIN: "🎃"}

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


def _today(clock: Clock | None) -> date:
    return (clock() if clock is not None else datetime.now(_PARIS)).astimezone(_PARIS).date()


def in_season(clock: Clock | None = None) -> bool:
    return FIRST_DAY <= _today(clock) <= LAST_DAY


def setup(app: PluginHost) -> None:
    for tag, plain in _FALLBACKS.items():
        FALLBACKS[tag] = plain  # repli Unicode si le bot ne voit pas l'emoji
        note_undo(lambda tag=tag: FALLBACKS.pop(tag, None))
    app.database.execute(_TABLE)
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
    PRIMARY KEY (guild_id, user_id)
)
"""


@dataclass(frozen=True, slots=True)
class _Who:
    guild: int
    user: int
    name: str


def halloween_capability(
    database: Database,
    *,
    clock: Clock | None = None,
    rng: random.Random | None = None,
) -> Capability:
    dice = rng or random.SystemRandom()

    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        who = _Who(context.guild_id or 0, context.user_id, context.author_name)
        today = _today(clock).isoformat()
        action = str(args.get("action") or "ring")
        if action == "ranking":
            data = await asyncio.to_thread(_ranking, database, who)
        elif action == "bag":
            data = await asyncio.to_thread(_bag, database, who, today)
        else:
            data = await asyncio.to_thread(_ring, database, who, today, dice)
        return Result(ok=True, data=data, widget="trick_or_treat")

    return Capability(
        name="trick_or_treat",
        description=(
            "Halloween, bonbons ou sort. action=ring quand quelqu'un sonne à ta porte, dit "
            "« bonbons ou sort » ou veut des bonbons (le tirage est fait par l'outil, jamais par "
            "toi ; 3 sonneries par jour et par personne) ; action=bag pour voir son sac de "
            "bonbons ; action=ranking pour le classement du serveur. Joue le jeu avec une touche "
            "macabre, brièvement : la carte affiche déjà le résultat."
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


def _ring(database: Database, who: _Who, today: str, dice: random.Random) -> dict[str, Any]:
    with database.transaction():
        _open_bag(database, who)
        row = database.fetchone(_BAG, (who.guild, who.user))
        rings = int(row["rings"]) if row is not None and row["day"] == today else 0
        candies = int(row["candies"]) if row is not None else 0
        tricks = int(row["tricks"]) if row is not None else 0
        if rings >= RINGS_PER_DAY:
            return _closed(candies, tricks)
        gained, stolen, outcome, gift = _draw(dice, candies)
        candies += gained - stolen
        tricks += outcome == "trick"
        database.execute(
            "UPDATE halloween_bag SET name = ?, candies = ?, tricks = ?, day = ?, rings = ? "
            "WHERE guild_id = ? AND user_id = ?",
            (who.name, candies, tricks, today, rings + 1, who.guild, who.user),
        )
    return {
        "action": "ring",
        "outcome": outcome,
        "gift": gift,
        "gained": gained,
        "stolen": stolen,
        "candies": candies,
        "rings_left": RINGS_PER_DAY - rings - 1,
    }


def _draw(dice: random.Random, candies: int) -> tuple[int, int, str, str]:
    """Bonbons gagnés, bonbons volés, `treat` ou `trick`, et le texte du cadeau ou du sort."""
    if dice.random() < _TRICK_CHANCE:
        trick, steal = dice.choice(_TRICKS)
        return 0, min(steal, candies), "trick", trick
    weights = [weight for _gift, _worth, weight in _TREATS]
    gift, worth, _weight = dice.choices(_TREATS, weights=weights)[0]
    return worth, 0, "treat", gift


def _closed(candies: int, tricks: int) -> dict[str, Any]:
    return {
        "action": "ring",
        "outcome": "closed",
        "candies": candies,
        "tricks": tricks,
        "rings_left": 0,
    }


def _open_bag(database: Database, who: _Who) -> None:
    database.execute(
        "INSERT INTO halloween_bag (guild_id, user_id, name) VALUES (?, ?, ?) "
        "ON CONFLICT (guild_id, user_id) DO NOTHING",
        (who.guild, who.user, who.name),
    )


_BAG = "SELECT * FROM halloween_bag WHERE guild_id = ? AND user_id = ?"


def _bag(database: Database, who: _Who, today: str) -> dict[str, Any]:
    row = database.fetchone(_BAG, (who.guild, who.user))
    if row is None:
        return {"action": "bag", "candies": 0, "tricks": 0, "rings_left": RINGS_PER_DAY}
    used = int(row["rings"]) if row["day"] == today else 0
    return {
        "action": "bag",
        "candies": int(row["candies"]),
        "tricks": int(row["tricks"]),
        "rings_left": max(0, RINGS_PER_DAY - used),
    }


def _ranking(database: Database, who: _Who) -> dict[str, Any]:
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
    action = str(data.get("action") or "")
    title = heading("Bonbons ou sort", "Halloween", emoji=_PUMPKIN)
    if action == "ranking":
        return _show_ranking(title, data)
    sack = f"Sac · {data.get('candies', 0)} {_CANDY}"
    if action == "bag":
        left = _rings_text(int(data.get("rings_left") or 0))
        body = f"**{data.get('candies', 0)}** {_CANDY} dans ton sac"
        body += f" · {data.get('tricks', 0)} sort(s) subi(s)"
        return Rendered(cards=(card(title, separator(wide=True), text(body), footer(left)),))
    outcome = data.get("outcome")
    if outcome == "closed":
        body = "La porte reste fermée… Reviens demain pour de nouvelles sonneries."
    elif outcome == "trick":
        lost = int(data.get("stolen") or 0)
        extra = f" (-{lost} {_CANDY})" if lost else ""
        body = f"**Un sort !** {data.get('gift')}{extra}"
    else:
        body = f"**Des bonbons !** Tu reçois {data.get('gift')} (+{data.get('gained')} {_CANDY})"
    foot = f"{sack}  ·  {_rings_text(int(data.get('rings_left') or 0))}"
    note = f"trick_or_treat : {outcome}, {data.get('candies', 0)} bonbons au total"
    return Rendered(cards=(card(title, separator(wide=True), text(body), footer(foot)),), note=note)


def _rings_text(left: int) -> str:
    if left <= 0:
        return "plus de sonnerie aujourd'hui"
    return f"{left} sonnerie{'s' if left > 1 else ''} restante{'s' if left > 1 else ''} aujourd'hui"


def _show_ranking(title: Any, data: Mapping[str, Any]) -> Rendered:
    board = data.get("board") or []
    if not board:
        body = "Personne n'a encore sonné ici. Qui ose frapper à la porte ?"
    else:
        medals = ("🥇", "🥈", "🥉")
        lines = []
        for rank, entry in enumerate(board):
            mark = medals[rank] if rank < len(medals) else f"{rank + 1}."
            name = f"**{entry['name']}**" if entry.get("me") else str(entry["name"])
            lines.append(f"{mark} {name} · {entry['candies']} {_CANDY}")
        body = "\n".join(lines)
    return Rendered(
        cards=(card(title, separator(wide=True), text(body), footer("Classement du serveur")),)
    )
