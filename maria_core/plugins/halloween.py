"""Halloween 2026 : « bonbons ou sort », un outil qui n'existe que du 15 octobre au 1er novembre.

Pour retirer l'événement : suivre RETRAIT_HALLOWEEN.md (à la racine du projet). L'outil
s'éteint de lui-même après le 1er novembre ; les tables `halloween_*` peuvent rester ou être
supprimées (DROP TABLE).
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
from maria_core.events import EventBus
from maria_core.ledger import note_undo
from maria_core.objectives.signals import ObjectiveSignal
from maria_core.plugins import PluginHost
from maria_core.plugins import halloween_store as store
from maria_core.plugins.halloween_store import Player, ensure_table
from maria_core.plugins.halloween_sweets import CANDY, SWEET_FALLBACKS
from maria_core.ui.emojis import FALLBACKS
from maria_core.ui.widgets import Rendered, card, footer, heading, separator, text

NAME = "halloween"
FIRST_DAY = date(2026, 10, 15)
LAST_DAY = date(2026, 11, 1)
_PARIS = ZoneInfo("Europe/Paris")
PUMPKIN = "<:pumpkin:1560363014048448594>"
GOBLET = "<:goblet:1560364573905780827>"
_FALLBACKS = {PUMPKIN: "🎃", GOBLET: "🏆", **SWEET_FALLBACKS}

type Clock = Callable[[], datetime]
type Watch = set[tuple[int, int]]

__all__ = ["CANDY", "Player", "ensure_table"]


@dataclass(frozen=True, slots=True)
class Reward:
    """Un gage respecté : le bot réagit au message avec le bonbon gagné."""

    guild_id: int
    channel_id: int
    message_id: int
    user_id: int
    emoji: str


def _now(clock: Clock | None) -> datetime:
    return (clock() if clock is not None else datetime.now(_PARIS)).astimezone(_PARIS)


def in_season(clock: Clock | None = None) -> bool:
    return FIRST_DAY <= _now(clock).date() <= LAST_DAY


def setup(app: PluginHost) -> None:
    for tag, plain in _FALLBACKS.items():
        FALLBACKS[tag] = plain  # repli Unicode si le bot ne voit pas l'emoji
        note_undo(lambda tag=tag: FALLBACKS.pop(tag, None))
    ensure_table(app.database)
    watch: Watch = store.active_dares(app.database)
    app.capabilities.register(halloween_capability(app.database, watch=watch))
    app.widgets.register("trick_or_treat", render_halloween)
    app.events.subscribe(ObjectiveSignal, dare_listener(app.database, app.events, watch))


async def play(
    database: Database,
    who: Player,
    action: str,
    *,
    clock: Clock | None = None,
    rng: random.Random | None = None,
    watch: Watch | None = None,
) -> dict[str, Any]:
    """`ring`, `bag` ou `ranking` : utilisé par l'outil du modèle et par le menu /halloween."""
    now = _now(clock)
    if action == "ranking":
        return await asyncio.to_thread(store.ranking, database, who)
    if action == "bag":
        return await asyncio.to_thread(store.bag, database, who, now)
    data = await asyncio.to_thread(store.ring, database, who, now, rng or random.SystemRandom())
    if data.get("dare") and watch is not None:
        watch.add((who.guild, who.user))
    return data


def halloween_capability(
    database: Database,
    *,
    clock: Clock | None = None,
    rng: random.Random | None = None,
    watch: Watch | None = None,
) -> Capability:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        who = Player(
            context.guild_id or 0, context.user_id, context.author_name, context.message_id or 0
        )
        action = str(args.get("action") or "ring")
        data = await play(database, who, action, clock=clock, rng=rng, watch=watch)
        return Result(ok=True, data=data, widget="trick_or_treat")

    return Capability(
        name="trick_or_treat",
        description=(
            "Halloween, bonbons ou sort. action=ring quand quelqu'un sonne à ta porte : « bonbons "
            "ou un sort », « trick or treat », « toc toc », « ding dong », « on frappe à ta "
            "porte », ou il veut des bonbons (le tirage est fait par l'outil, jamais par "
            "toi ; une sonnerie toutes les 3 h et 4 par jour au plus, par personne) ; "
            "action=bag pour voir son sac de bonbons ; action=ranking pour le classement du "
            "serveur. Un sort peut être un gage : l'outil le vérifie tout seul sur les messages "
            "suivants et le bot réagit avec un bonbon, ne le vérifie pas toi-même. Joue le jeu "
            "avec une touche macabre, brièvement : la carte affiche déjà le résultat."
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


def dare_listener(
    database: Database,
    events: EventBus,
    watch: Watch,
    *,
    clock: Clock | None = None,
    rng: random.Random | None = None,
) -> Callable[[ObjectiveSignal], Any]:
    """Chaque message de quelqu'un qui a un gage : respecté, le bot réagit avec un bonbon."""
    dice = rng or random.SystemRandom()

    async def on_signal(signal: ObjectiveSignal) -> None:
        if signal.kind != "message" or signal.author_is_bot or signal.guild_id is None:
            return
        key = (signal.guild_id, signal.user_id)
        if key not in watch or signal.message_id is None:
            return
        who = Player(signal.guild_id, signal.user_id, signal.author_name)
        sweet, done = await asyncio.to_thread(
            store.judge, database, who, signal.text, signal.message_id, _now(clock), dice
        )
        if done:
            watch.discard(key)
        if sweet is not None:
            events.publish_soon(
                Reward(
                    guild_id=signal.guild_id,
                    channel_id=_channel_of(signal),
                    message_id=signal.message_id,
                    user_id=signal.user_id,
                    emoji=sweet.emoji,
                )
            )

    return on_signal


def _channel_of(signal: ObjectiveSignal) -> int:
    """Le salon réel du message (un fil, pas son salon parent), lu dans le lien du message."""
    parts = signal.url.rstrip("/").rsplit("/", 2)
    if len(parts) == 3 and parts[1].isdigit():
        return int(parts[1])
    return signal.channel_id


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
        return _bag_text(data)
    outcome = data.get("outcome")
    if outcome == "closed":
        if data.get("reason") == "wait" and data.get("next_at"):
            return f"La porte reste fermée… Reviens <t:{data['next_at']}:R>."
        return "La porte reste fermée… Reviens demain pour de nouvelles sonneries."
    if outcome == "trick":
        lost = int(data.get("stolen") or 0)
        extra = f" (-{lost} {CANDY})" if lost else ""
        line = f"**Un sort !** {data.get('gift')}{extra}"
        if data.get("dare"):
            line += "\n-# Réussis-le : je réagirai à ton message avec un bonbon en plus (+1)."
        return line
    gain = f"+{data.get('gained')} {data.get('emoji')}"
    return f"**Des bonbons !** Tu reçois {data.get('gift')} ({gain})"


def _bag_text(data: Mapping[str, Any]) -> str:
    lines = [
        f"**{data.get('candies', 0)}** {CANDY} dans ton sac"
        f" · {data.get('tricks', 0)} sort(s) subi(s)"
    ]
    sweets = data.get("sweets") or []
    if sweets:
        lines.append("  ".join(f"{emoji} {count}" for emoji, count in sweets))
    dare = data.get("dare")
    if dare:
        lines.append(f"**Gage en cours** · {dare['text']}\n-# Expire <t:{dare['expires_at']}:R>")
    return "\n".join(lines)


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
