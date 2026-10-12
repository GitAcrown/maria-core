"""Une activation : condition avant, lecture, condition après, puis le message. Repris de task_plan.

Rien n'est envoyé si une condition est fausse ou invérifiable : le silence est le défaut.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from maria_core.db import Database
from maria_core.objectives.compile import PRICE_CONDITIONS
from maria_core.objectives.model import Objective
from maria_core.objectives.price import Candidate, ambiguous, candidates, price_holds
from maria_core.objectives.quota import budget_key, take_fetch
from maria_core.objectives.schedule import PARIS, describe
from maria_core.objectives.signals import ObjectiveSignal
from maria_core.ui.widgets import Card

_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_PAGE_CHARS = 1500
_SNAPSHOT = 300

type Fetcher = Callable[[str], Awaitable[str]]
type Searcher = Callable[[str], Awaitable[tuple[str, str]]]
type Judge = Callable[[str, str], Awaitable[bool]]
type PricePicker = Callable[[list[str]], Awaitable[int | None]]


@dataclass(frozen=True, slots=True)
class Delivery:
    text: str
    cards: tuple[Card, ...] = ()
    footer: str = ""
    mention: bool = True
    reply_to: int | None = None


@dataclass(frozen=True, slots=True)
class Written:
    text: str
    cards: tuple[Card, ...] = ()


class Writer(Protocol):
    async def write(
        self,
        objective: Objective,
        instruction: str,
        evidence: str,
        runs: tuple[tuple[str, str], ...],
    ) -> Written | None: ...


@dataclass(slots=True)
class Pass:
    """État d'un passage : preuve accumulée, prix lu, URL utile."""

    evidence: str
    state: dict[str, Any]
    price: float | None = None
    previous: float | None = None
    url: str = ""
    page: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Outcome:
    kind: str
    state: Mapping[str, Any]
    summary: str = ""
    delivery: Delivery | None = None


class Pipeline:
    def __init__(
        self,
        database: Database,
        *,
        fetcher: Fetcher,
        searcher: Searcher | None = None,
        judge: Judge | None = None,
        writer: Writer | None = None,
        picker: PricePicker | None = None,
    ) -> None:
        self._database = database
        self._fetcher = fetcher
        self.searcher = searcher
        self.judge = judge
        self.writer = writer
        self.picker = picker

    async def run(
        self,
        objective: Objective,
        *,
        now: datetime,
        signal: ObjectiveSignal | None,
        runs: tuple[tuple[str, str], ...] = (),
    ) -> Outcome:
        current = Pass(
            evidence=trigger_evidence(now, signal, objective.state), state=dict(objective.state)
        )
        condition = objective.condition
        if _before(condition) and not await self._judge(condition, current.evidence):
            return Outcome("skipped", current.state)
        if objective.action.get("type") == "fetch_then":
            fetched = await self._fetch(objective, current, now)
            if fetched != "ok":
                return Outcome(fetched, current.state)
        after = condition is not None and not _before(condition)
        if after and not await self._holds(condition, current):
            return Outcome("skipped", current.state)
        delivery = await self._compose(objective, current, signal, runs)
        if delivery is None:
            return Outcome("skipped", current.state)
        if condition is not None and condition.get("type") in PRICE_CONDITIONS:
            current.state["alerted_price"] = current.price
        return Outcome("sent", current.state, delivery.text[:400], delivery)

    async def _fetch(self, objective: Objective, current: Pass, now: datetime) -> str:
        key = budget_key(objective.guild_id, objective.owner_id)
        allowed = await asyncio.to_thread(take_fetch, self._database, objective.id, key, now)
        if not allowed:
            return "budget"
        url = str(objective.action.get("url") or "")
        query = str(objective.action.get("query") or "")
        if url:
            page = await self._fetcher(url)
        elif self.searcher is not None:
            page, url = await self.searcher(query)
        else:
            page = ""
        if not page.strip():
            return "skipped"
        current.url = url
        current.page = " ".join(page.split())[:_PAGE_CHARS]
        await self._price(current, page)
        if current.price is not None:
            current.page = f"Prix détecté : {current.price:.2f} €. {current.page}"
        current.evidence = f"{current.evidence}\n\nPage :\n{current.page}".strip()
        current.state["last_result"] = current.page[:_SNAPSHOT]
        return "ok"

    async def _price(self, current: Pass, page: str) -> None:
        found = candidates(page[:8000], str(current.state.get("anchor") or ""))
        if not found:
            return
        best = await self._choose(found)
        current.previous = _number(current.state.get("price"))
        current.price = best.value
        current.state["price"] = best.value
        if len("".join(ch for ch in best.anchor if ch.isalnum())) >= 4:
            current.state["anchor"] = best.anchor

    async def _choose(self, found: list[Candidate]) -> Candidate:
        close = ambiguous(found)
        if not close or self.picker is None:
            return found[0]
        index = await self.picker([item.snippet for item in close])
        return close[index] if index is not None and 0 <= index < len(close) else found[0]

    async def _holds(self, condition: Mapping[str, Any], current: Pass) -> bool:
        if condition.get("type") in PRICE_CONDITIONS:
            if not price_holds(condition, current.price, current.previous):
                return False
            alerted = _number(current.state.get("alerted_price"))
            return alerted is None or current.price is None or abs(current.price - alerted) >= 0.01
        return await self._judge(condition, current.evidence)

    async def _judge(self, condition: Mapping[str, Any] | None, evidence: str) -> bool:
        text = str((condition or {}).get("text") or "").strip()
        if not text or not evidence.strip() or self.judge is None:
            return False
        return await self.judge(text, evidence)

    async def _compose(
        self,
        objective: Objective,
        current: Pass,
        signal: ObjectiveSignal | None,
        runs: tuple[tuple[str, str], ...],
    ) -> Delivery | None:
        action = objective.action
        kind = str(action.get("type") or "remind")
        instruction = str(action.get("text") or objective.title)
        footer = _footer(objective, current, signal)
        mention = signal is None or signal.user_id != objective.owner_id
        reply_to = objective.origin_message_id if signal is None else None
        if kind == "report" or (kind == "fetch_then" and action.get("write")):
            written = await self._written(objective, instruction, current, runs)
            if written is None:
                return None
            return Delivery(written.text, written.cards, footer, mention, reply_to)
        text = _plain(kind, instruction, current, signal)
        return Delivery(text, footer=footer, mention=mention, reply_to=reply_to)

    async def _written(
        self,
        objective: Objective,
        instruction: str,
        current: Pass,
        runs: tuple[tuple[str, str], ...],
    ) -> Written | None:
        if self.writer is None:
            return Written(instruction)
        evidence = current.evidence
        if objective.condition is not None and not _before(objective.condition):
            evidence += "\n(La condition est déjà vérifiée : ne réponds pas [[SILENCE]].)"
        return await self.writer.write(objective, instruction, evidence, runs)


def trigger_evidence(
    now: datetime, signal: ObjectiveSignal | None, state: Mapping[str, Any]
) -> str:
    local = now.astimezone(PARIS)
    lines = [f"Moment : {_DAYS[local.weekday()]} {local:%Y-%m-%d %H:%M} (Paris)."]
    if signal is not None:
        lines.append(signal.fact())
    previous = str(state.get("last_result") or "").strip()
    if previous:
        lines.insert(0, f"Résultat précédent de cet objectif :\n{previous[:_SNAPSHOT]}\n")
    return "\n".join(lines)


def _plain(kind: str, instruction: str, current: Pass, signal: ObjectiveSignal | None) -> str:
    if current.price is not None:
        was = ""
        if current.previous is not None and abs(current.previous - current.price) >= 0.01:
            was = f", avant {current.previous:.2f} €"
        fact = f"le prix est à **{current.price:.2f} €**{was}"
        if "{price}" in instruction:
            head = instruction.replace("{price}", f"{current.price:.2f}")
        else:
            head = f"{instruction} — {fact}" if instruction else fact
        return f"{head}\n<{current.url}>" if current.url else head
    if kind == "fetch_then":
        clip = instruction or current.page[:180]
        return f"{clip}\n<{current.url}>" if current.url else clip
    text = instruction or "C'est l'heure."
    if signal is not None and signal.kind == "message" and signal.text:
        return f"{text}\n> {' '.join(signal.text.split())[:160]}"
    if signal is not None:
        return f"{text}\n> {signal.fact()}"
    return text


def _footer(objective: Objective, current: Pass, signal: ObjectiveSignal | None) -> str:
    fires = objective.fires + 1
    limit = objective.max_fires
    count = f"alerte {fires}/{limit or '∞'}"
    done = " · écoute terminée" if limit is not None and fires >= limit else ""
    if signal is not None and signal.url:
        return f"**Écoute** · [message](<{signal.url}>) · {count}{done}"
    if signal is not None:
        return f"**Écoute** · {signal.fact()[:100]} · {count}{done}"
    if current.price is not None:
        threshold = (objective.condition or {}).get("threshold")
        limit_text = (
            f" · seuil {float(threshold):g} €" if isinstance(threshold, int | float) else ""
        )
        return f"**Veille** · {current.price:.2f} €{limit_text}"
    if objective.action.get("type") == "fetch_then":
        return "**Veille** · " + describe(objective.trigger)
    if objective.trigger.get("type") == "at":
        return "**Rappel**"
    return "**Programmé** · " + describe(objective.trigger)


def _before(condition: Mapping[str, Any] | None) -> bool:
    return (
        condition is not None
        and condition.get("type") == "judge"
        and (condition.get("when") == "before")
    )


def _number(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return float(raw)
