"""Exécute un objectif déjà réservé. Un créneau déjà enregistré n'est pas renvoyé."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from maria_core.db import Database
from maria_core.objectives.model import Objective, StaleObjective
from maria_core.objectives.pipeline import Delivery, Fetcher, Judge, Outcome, Pipeline, Writer
from maria_core.objectives.quota import STORM_PER_HOUR, fires_last_hour, next_budget_day
from maria_core.objectives.schedule import EVENT_TRIGGERS, local_text, next_due, time_key
from maria_core.objectives.signals import ObjectiveSignal
from maria_core.objectives.store import ObjectiveStore

logger = logging.getLogger(__name__)

MISSED_AFTER = timedelta(hours=6)
_BACKOFF = (30, 120, 600)


class Courier(Protocol):
    async def send(self, objective: Objective, delivery: Delivery) -> None: ...

    async def notify(self, objective: Objective, text: str) -> None: ...


class Runner:
    def __init__(
        self,
        store: ObjectiveStore,
        database: Database,
        *,
        clock: Callable[[], datetime] | None = None,
        fetcher: Fetcher | None = None,
        writer: Writer | None = None,
        judge: Judge | None = None,
    ) -> None:
        self._store = store
        self._database = database
        self._clock = clock or _now
        self.pipeline = Pipeline(database, fetcher=fetcher or _empty_fetch, judge=judge)
        self.pipeline.writer = writer
        self.courier: Courier | None = None

    async def execute(
        self,
        objective: Objective,
        *,
        key: str | None = None,
        signal: ObjectiveSignal | None = None,
    ) -> str:
        try:
            return await self._run(objective, key, signal)
        except Exception:
            await asyncio.to_thread(self._store.release, objective.id, objective.version)
            raise

    async def _run(
        self, objective: Objective, key: str | None, signal: ObjectiveSignal | None
    ) -> str:
        now = self._clock()
        if objective.expires_at is not None and objective.expires_at <= now:
            await self._settle(
                objective,
                now=now,
                status="done",
                next_run_at=None,
                fires=objective.fires,
                state=objective.state,
            )
            return "expired"
        if (
            signal is not None
            and await asyncio.to_thread(fires_last_hour, self._database, objective.id, now)
            >= STORM_PER_HOUR
        ):
            return "storm"
        activation = key or time_key(objective.next_run_at)
        gate = await asyncio.to_thread(self._store.open_run, objective.id, activation, now)
        if gate == "busy":
            return "busy"
        if gate == "done":
            await self._skip(objective, now)
            return "duplicate"
        if _late(objective, now):
            return await self._missed(objective, activation, now)
        return await self._perform(objective, activation, now, signal)

    async def _perform(
        self, objective: Objective, activation: str, now: datetime, signal: ObjectiveSignal | None
    ) -> str:
        try:
            runs = await asyncio.to_thread(self._store.recent_summaries, objective.id)
            outcome = await self.pipeline.run(objective, now=now, signal=signal, runs=runs)
            if outcome.delivery is not None:
                await self._send(objective, outcome.delivery)
        except Exception as exc:
            logger.exception("Objectif %s en échec", objective.id)
            await self._failed(objective, activation, now, exc)
            return "failed"
        await asyncio.to_thread(
            self._store.complete_run,
            objective.id,
            activation,
            outcome.kind,
            "",
            now,
            outcome.summary,
        )
        await self._move(objective, now, outcome)
        return outcome.kind

    async def _missed(self, objective: Objective, activation: str, now: datetime) -> str:
        when = local_text(objective.next_run_at.isoformat()) if objective.next_run_at else "?"
        text = str(objective.action.get("text") or objective.title)
        await self._notify(objective, f"Rappel manqué ({when}) : {text}")
        await asyncio.to_thread(
            self._store.complete_run, objective.id, activation, "missed", "", now
        )
        await self._move(objective, now, Outcome("missed", objective.state))
        return "missed"

    async def _failed(self, objective: Objective, key: str, now: datetime, exc: Exception) -> None:
        attempts = int(objective.state.get("attempts") or 0) + 1
        state = {**objective.state, "attempts": attempts}
        await asyncio.to_thread(
            self._store.complete_run, objective.id, key, "failed", str(exc), now
        )
        if attempts > len(_BACKOFF):
            await self._notify(objective, f"Objectif « {objective.title} » en échec : {exc}")
            await self._settle(
                objective,
                now=now,
                status="failed",
                next_run_at=None,
                fires=objective.fires,
                state=state,
                error=str(exc),
            )
            return
        retry = now + timedelta(seconds=_BACKOFF[attempts - 1])
        if objective.next_run_at is None and str(objective.trigger.get("type")) in EVENT_TRIGGERS:
            retry = None
        await self._settle(
            objective,
            now=now,
            status="active",
            next_run_at=retry,
            fires=objective.fires,
            state=state,
            error=str(exc),
        )

    async def _move(self, objective: Objective, now: datetime, outcome: Outcome) -> None:
        fired = outcome.kind == "sent"
        updated: dict[str, Any] = dict(outcome.state)
        fires = objective.fires + (1 if fired else 0)
        status, nxt = _next_status(objective, now, fires, outcome.kind)
        if fired:
            updated["last_fire_at"] = now.isoformat()
            updated["attempts"] = 0
        await self._settle(
            objective, now=now, status=status, next_run_at=nxt, fires=fires, state=updated
        )

    async def _skip(self, objective: Objective, now: datetime) -> None:
        try:
            await self._move(objective, now, Outcome("skipped", objective.state))
        except StaleObjective:
            await asyncio.to_thread(self._store.release, objective.id, objective.version)

    async def _settle(self, objective: Objective, **fields: object) -> None:
        await asyncio.to_thread(self._store.settle, objective, **fields)

    async def _send(self, objective: Objective, delivery: Delivery) -> None:
        if self.courier is None:
            raise RuntimeError("Aucun canal pour envoyer l'objectif.")
        await self.courier.send(objective, delivery)

    async def _notify(self, objective: Objective, text: str) -> None:
        if self.courier is not None:
            await self.courier.notify(objective, text)


def _next_status(
    objective: Objective, now: datetime, fires: int, outcome: str
) -> tuple[str, datetime | None]:
    kind = str(objective.trigger.get("type") or "")
    if outcome == "budget":
        if kind in EVENT_TRIGGERS:
            return "active", None
        return "active", next_budget_day(now)
    if objective.max_fires is not None and fires >= objective.max_fires:
        return "done", None
    nxt = next_due(objective.trigger, after=now)
    if nxt is None and kind not in EVENT_TRIGGERS:
        return "done", None
    return "active", nxt


def _late(objective: Objective, now: datetime) -> bool:
    if objective.next_run_at is None:
        return False
    return now - objective.next_run_at > MISSED_AFTER


async def _empty_fetch(_url: str) -> str:
    return ""


def _now() -> datetime:
    return datetime.now(UTC)
