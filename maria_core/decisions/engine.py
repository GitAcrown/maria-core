"""Une décision : règle, cache, modèle, repli. Dans cet ordre, et journalisée."""

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Protocol

from maria_core.db import Database
from maria_core.decisions.cache import MemoryCache
from maria_core.decisions.registry import Decision, DecisionRegistry
from maria_core.decisions.types import (
    DecisionPath,
    Question,
    RuleHit,
    StructuredAnswer,
    Verdict,
)

logger = logging.getLogger(__name__)

type Clock = Callable[[], datetime]


class Decider(Protocol):
    async def resolve(self, name: str, state: Mapping[str, Any]) -> Verdict: ...


class StructuredBackend(Protocol):
    async def ask(
        self,
        state: Mapping[str, Any],
        question: Question,
    ) -> StructuredAnswer | None: ...

    async def close(self) -> None: ...


class DecisionEngine:
    def __init__(
        self,
        registry: DecisionRegistry,
        backend: StructuredBackend,
        database: Database,
        *,
        cache: MemoryCache | None = None,
        now: Clock | None = None,
    ) -> None:
        self._registry = registry
        self._backend = backend
        self._database = database
        self._cache = cache or MemoryCache()
        self._now = now or _utc_now
        self._inflight: dict[str, int] = {}

    async def resolve(self, name: str, state: Mapping[str, Any]) -> Verdict:
        started = perf_counter()
        decision = self._registry.get(name)
        digest = digest_state(name, state)
        ruled = self._rules(decision, state)
        if ruled is not None:
            return await self._commit(
                decision, digest, "rules", ruled.value, ruled.confidence, started
            )
        cached = self._cache.get(digest)
        if cached is not None:
            return await self._commit(decision, digest, "cache", cached[0], cached[1], started)
        return await self._model_or_fallback(decision, state, digest, started)

    async def _model_or_fallback(
        self,
        decision: Decision,
        state: Mapping[str, Any],
        digest: str,
        started: float,
    ) -> Verdict:
        self._inflight[decision.name] = self._inflight.get(decision.name, 0) + 1
        try:
            answer = await self._ask(decision, state)
        finally:
            self._inflight[decision.name] -= 1
        if answer is None:
            return await self._fallback(decision, digest, None, started)
        if answer.confidence < decision.threshold:
            return await self._fallback(decision, digest, answer.confidence, started)
        self._cache.put(digest, answer.value, answer.confidence, decision.cache_ttl_s)
        return await self._commit(
            decision, digest, "model", answer.value, answer.confidence, started
        )

    def _rules(self, decision: Decision, state: Mapping[str, Any]) -> RuleHit | None:
        if decision.rules is None:
            return None
        try:
            result = decision.rules(state)
        except Exception:
            logger.exception("Règle %s en échec", decision.name)
            return None
        if isinstance(result, RuleHit):
            return result
        return None

    async def _ask(
        self,
        decision: Decision,
        state: Mapping[str, Any],
    ) -> StructuredAnswer | None:
        if decision.question is None or not await self._allow(decision):
            return None
        return await self._backend.ask(dict(state), decision.question)

    async def _allow(self, decision: Decision) -> bool:
        """Les appels en cours, celui-ci compris, sont déjà réservés."""
        limit = decision.budget_per_day
        if limit is None:
            return True
        if limit <= 0:
            return False
        spent = await asyncio.to_thread(self._spent, decision.name)
        return spent + self._inflight.get(decision.name, 0) <= limit

    def _spent(self, name: str) -> int:
        start = self._now().astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        row = self._database.fetchone(
            """
            SELECT COUNT(*) AS n FROM decision_log
            WHERE name = ? AND path = 'model' AND at >= ?
            """,
            (name, start.isoformat()),
        )
        if row is None:
            return 0
        return int(row["n"])

    async def _fallback(
        self,
        decision: Decision,
        digest: str,
        confidence: float | None,
        started: float,
    ) -> Verdict:
        return await self._commit(
            decision, digest, "fallback", decision.fallback, confidence, started
        )

    async def _commit(
        self,
        decision: Decision,
        digest: str,
        path: DecisionPath,
        value: Any,
        confidence: float | None,
        started: float,
    ) -> Verdict:
        elapsed = max(0, int((perf_counter() - started) * 1000))
        row = (self._now().isoformat(), decision.name, digest, path, _text(value), confidence)
        await asyncio.to_thread(_write, self._database, (*row, elapsed))
        logger.info("Décision %s chemin=%s", decision.name, path)
        return Verdict(name=decision.name, value=value, path=path, confidence=confidence)


def digest_state(name: str, state: Mapping[str, Any]) -> str:
    payload = json.dumps(state, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{name}\n{payload}".encode()).hexdigest()[:16]


def _write(database: Database, row: tuple[object, ...]) -> None:
    try:
        database.execute(
            """
            INSERT INTO decision_log (
                at, name, input_hash, path, verdict, confidence, duration_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )
    except Exception:
        logger.exception("Journal de décision impossible pour %s", row[1])


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value[:300]
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:300]
    except TypeError:
        return str(value)[:300]


def _utc_now() -> datetime:
    return datetime.now(UTC)
