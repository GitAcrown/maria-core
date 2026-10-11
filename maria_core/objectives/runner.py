"""Exécute un objectif déjà réservé. Un créneau déjà enregistré n'est pas renvoyé."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from maria_core.db import Database
from maria_core.objectives.model import Objective, StaleObjective
from maria_core.objectives.price import extract_price
from maria_core.objectives.quota import fetches_allowed, next_budget_day
from maria_core.objectives.schedule import EVENT_TRIGGERS, next_due, time_key
from maria_core.objectives.store import ObjectiveStore

logger = logging.getLogger(__name__)

MISSED_AFTER = timedelta(hours=6)
_BACKOFF = (30, 120, 600)

type Fetcher = Callable[[str], Awaitable[str]]
type Writer = Callable[[str], Awaitable[str]]
type Judge = Callable[[str, str], Awaitable[bool]]


class Courier(Protocol):
    async def send(self, objective: Objective, text: str) -> None: ...

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
        self._fetcher = fetcher or _empty_fetch
        self._writer = writer or _echo
        self._judge = judge
        self.courier: Courier | None = None

    async def execute(self, objective: Objective, *, key: str | None = None) -> str:
        try:
            return await self._run(objective, key)
        except Exception:
            await asyncio.to_thread(self._store.release, objective.id, objective.version)
            raise

    async def _run(self, objective: Objective, key: str | None) -> str:
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
        activation = key or time_key(objective.next_run_at)
        gate = await asyncio.to_thread(self._store.open_run, objective.id, activation, now)
        if gate == "busy":
            return "busy"
        if gate == "done":
            await self._skip(objective, now)
            return "duplicate"
        if _late(objective, now):
            await self._notify(objective, f"Rappel manqué : {objective.title}")
            await asyncio.to_thread(
                self._store.complete_run, objective.id, activation, "missed", "", now
            )
            await self._move(objective, now, fired=False, state=dict(objective.state))
            return "missed"
        try:
            outcome, state = await self._perform(objective)
        except Exception as exc:
            logger.exception("Objectif %s en échec", objective.id)
            await self._failed(objective, activation, now, exc)
            return "failed"
        await asyncio.to_thread(
            self._store.complete_run, objective.id, activation, outcome, "", now
        )
        await self._move(objective, now, fired=outcome == "sent", state=state, outcome=outcome)
        return outcome

    async def _perform(self, objective: Objective) -> tuple[str, dict[str, Any]]:
        state = dict(objective.state)
        if str(objective.action.get("type")) == "fetch_then":
            return await self._fetch(objective, state)
        await self._send(objective, await self._text(objective))
        return "sent", state

    async def _fetch(
        self, objective: Objective, state: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        allowed = await asyncio.to_thread(fetches_allowed, self._database, self._clock())
        if not allowed:
            return "budget", state
        page = await self._fetcher(str(objective.action.get("url") or ""))
        price = extract_price(page)
        previous = _number(state.get("price"))
        if price is not None:
            state["price"] = price
        if not await self._holds(objective, page, price, previous):
            return "skipped", state
        body = str(objective.action.get("text") or page[:400])
        if price is not None:
            body = body.replace("{price}", f"{price:.2f}")
        await self._send(objective, body)
        return "sent", state

    async def _holds(
        self,
        objective: Objective,
        page: str,
        price: float | None,
        previous: float | None,
    ) -> bool:
        condition = objective.condition
        if condition is None:
            return True
        if condition.get("type") == "judge":
            if self._judge is None:
                return False
            return await self._judge(str(condition.get("text") or ""), page)
        return _price_holds(condition, price, previous)

    async def _text(self, objective: Objective) -> str:
        raw = str(objective.action.get("text") or objective.title)
        if str(objective.action.get("type")) == "report":
            return (await self._writer(raw)).strip() or raw
        return raw

    async def _failed(self, objective: Objective, key: str, now: datetime, exc: Exception) -> None:
        attempts = int(objective.state.get("attempts") or 0) + 1
        state = {**objective.state, "attempts": attempts}
        await asyncio.to_thread(
            self._store.complete_run, objective.id, key, "failed", str(exc), now
        )
        if attempts > len(_BACKOFF):
            await self._notify(objective, f"Objectif « {objective.title} » en échec.")
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
        await self._settle(
            objective,
            now=now,
            status="active",
            next_run_at=now + timedelta(seconds=_BACKOFF[attempts - 1]),
            fires=objective.fires,
            state=state,
            error=str(exc),
        )

    async def _move(
        self,
        objective: Objective,
        now: datetime,
        *,
        fired: bool,
        state: Mapping[str, Any],
        outcome: str = "sent",
    ) -> None:
        updated = dict(state)
        fires = objective.fires + (1 if fired else 0)
        status, nxt = _next_status(objective, now, fires, outcome)
        if fired:
            updated["last_fire_at"] = now.isoformat()
            updated["attempts"] = 0
        await self._settle(
            objective,
            now=now,
            status=status,
            next_run_at=nxt,
            fires=fires,
            state=updated,
        )

    async def _skip(self, objective: Objective, now: datetime) -> None:
        try:
            await self._move(objective, now, fired=False, state=objective.state)
        except StaleObjective:
            await asyncio.to_thread(self._store.release, objective.id, objective.version)

    async def _settle(self, objective: Objective, **fields: object) -> None:
        await asyncio.to_thread(self._store.settle, objective, **fields)

    async def _send(self, objective: Objective, text: str) -> None:
        if self.courier is None:
            raise RuntimeError("Aucun canal pour envoyer l'objectif.")
        await self.courier.send(objective, text)

    async def _notify(self, objective: Objective, text: str) -> None:
        if self.courier is not None:
            await self.courier.notify(objective, text)


def _next_status(
    objective: Objective,
    now: datetime,
    fires: int,
    outcome: str,
) -> tuple[str, datetime | None]:
    if outcome == "budget":
        return "active", next_budget_day(now)
    if objective.max_fires is not None and fires >= objective.max_fires:
        return "done", None
    nxt = next_due(objective.trigger, after=now)
    kind = str(objective.trigger.get("type") or "")
    if nxt is None and kind not in EVENT_TRIGGERS:
        return "done", None
    return "active", nxt


def _late(objective: Objective, now: datetime) -> bool:
    if objective.next_run_at is None:
        return False
    return now - objective.next_run_at > MISSED_AFTER


def _price_holds(
    condition: Mapping[str, Any],
    price: float | None,
    previous: float | None,
) -> bool:
    kind = str(condition.get("type") or "")
    if kind == "price_below":
        return price is not None and price < float(condition["threshold"])
    if kind == "price_above":
        return price is not None and price > float(condition["threshold"])
    if kind == "price_drop":
        if price is None or previous is None or previous <= 0:
            return False
        return (previous - price) / previous * 100 >= float(condition["percent"])
    return True


def _number(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return float(raw)


async def _empty_fetch(_url: str) -> str:
    return ""


async def _echo(prompt: str) -> str:
    return prompt


def _now() -> datetime:
    return datetime.now(UTC)
