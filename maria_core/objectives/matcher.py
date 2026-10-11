"""Relie un événement aux objectifs qui l'écoutent."""

import asyncio
from datetime import datetime, timedelta

from maria_core.objectives.model import Objective
from maria_core.objectives.runner import Runner
from maria_core.objectives.signals import ObjectiveSignal
from maria_core.objectives.store import ObjectiveStore


class Matcher:
    def __init__(self, store: ObjectiveStore, runner: Runner) -> None:
        self._store = store
        self._runner = runner

    async def handle(self, signal: ObjectiveSignal, *, now: datetime) -> int:
        fired = 0
        for objective in await asyncio.to_thread(self._store.event_objectives):
            if not _matches(objective, signal) or _cooling(objective, now):
                continue
            await self._runner.execute(objective, key=signal.key)
            fired += 1
        return fired


def _matches(objective: Objective, signal: ObjectiveSignal) -> bool:
    if objective.guild_id is not None and objective.guild_id != signal.guild_id:
        return False
    kind = str(objective.trigger.get("type") or "")
    if kind in {"on_voice", "on_member_join"}:
        return (kind == "on_voice" and signal.kind == "voice") or (
            kind == "on_member_join" and signal.kind == "join"
        )
    if objective.channel_ids and signal.channel_id not in objective.channel_ids:
        return False
    if kind == "on_message":
        return signal.kind == "message"
    if kind == "on_reply_to":
        return signal.kind == "message" and signal.reply_to_bot
    if kind == "on_topic":
        pattern = str(objective.trigger.get("pattern") or "").casefold()
        return signal.kind == "message" and bool(pattern) and pattern in signal.text.casefold()
    return False


def _cooling(objective: Objective, now: datetime) -> bool:
    if objective.cooldown_s <= 0:
        return False
    raw = objective.state.get("last_fire_at")
    if not isinstance(raw, str):
        return False
    last = datetime.fromisoformat(raw)
    if last.tzinfo is None:
        return False
    return now - last < timedelta(seconds=objective.cooldown_s)
