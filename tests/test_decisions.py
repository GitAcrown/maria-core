"""Règle, cache, modèle, repli. Le journal distingue les quatre chemins."""

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from maria_core.db import Database
from maria_core.decisions.cache import MemoryCache
from maria_core.decisions.catalog import builtin_decisions
from maria_core.decisions.engine import DecisionEngine
from maria_core.decisions.registry import Decision, DecisionRegistry
from maria_core.decisions.structured import JevBackend, read_answer
from maria_core.decisions.types import Question, RuleHit, StructuredAnswer


class _Backend:
    def __init__(self, answer: StructuredAnswer | None) -> None:
        self.answer = answer
        self.calls = 0

    async def ask(self, state: dict[str, object], question: Question) -> StructuredAnswer | None:
        self.calls += 1
        return self.answer

    async def close(self) -> None:
        return None


def _engine(
    tmp_path: Path,
    backend: _Backend,
    *,
    rules: Callable[[Mapping[str, Any]], RuleHit | None] | None = None,
    budget: int | None = 5,
    ttl: float = 30,
    clock: list[float] | None = None,
) -> tuple[DecisionEngine, Database, list[float]]:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    registry = DecisionRegistry()
    registry.register(
        Decision(
            name="sample",
            threshold=0.6,
            fallback="fallback",
            rules=rules,
            question=Question(instructions="Choisis.", criteria={"yes": "oui", "no": "non"}),
            cache_ttl_s=ttl,
            budget_per_day=budget,
        )
    )
    ticks = clock if clock is not None else [0.0]
    engine = DecisionEngine(
        registry,
        backend,
        database,
        cache=MemoryCache(clock=lambda: ticks[0]),
    )
    return engine, database, ticks


async def test_rules_do_not_call_the_model(tmp_path: Path) -> None:
    backend = _Backend(StructuredAnswer("no", 1.0))
    engine, database, _ticks = _engine(tmp_path, backend, rules=lambda _state: RuleHit("yes", 1.0))
    verdict = await engine.resolve("sample", {"text": "x"})
    assert verdict.path == "rules"
    assert verdict.value == "yes"
    assert backend.calls == 0
    row = database.fetchone("SELECT path FROM decision_log")
    assert row is not None
    assert row["path"] == "rules"
    database.close()


async def test_model_answer_is_cached_until_it_expires(tmp_path: Path) -> None:
    clock = [0.0]
    backend = _Backend(StructuredAnswer("yes", 0.9))
    engine, database, ticks = _engine(tmp_path, backend, clock=clock, ttl=10)
    first = await engine.resolve("sample", {"text": "x"})
    second = await engine.resolve("sample", {"text": "x"})
    assert first.path == "model"
    assert second.path == "cache"
    assert backend.calls == 1
    ticks[0] = 11
    third = await engine.resolve("sample", {"text": "x"})
    assert third.path == "model"
    assert backend.calls == 2
    database.close()


async def test_low_confidence_and_silence_use_the_fallback(tmp_path: Path) -> None:
    unsure = _Backend(StructuredAnswer("yes", 0.2))
    engine, database, _ticks = _engine(tmp_path, unsure)
    verdict = await engine.resolve("sample", {"text": "x"})
    assert verdict.path == "fallback"
    assert verdict.value == "fallback"
    database.close()

    silent = _Backend(None)
    engine, database, _ticks = _engine(tmp_path / "other", silent)
    verdict = await engine.resolve("sample", {"text": "x"})
    assert verdict.path == "fallback"
    assert silent.calls == 1
    database.close()


async def test_exhausted_budget_skips_the_model(tmp_path: Path) -> None:
    backend = _Backend(StructuredAnswer("yes", 0.9))
    engine, database, _ticks = _engine(tmp_path, backend, budget=1)
    assert (await engine.resolve("sample", {"n": 1})).path == "model"
    assert (await engine.resolve("sample", {"n": 2})).path == "fallback"
    assert backend.calls == 1
    database.close()


async def test_zero_budget_never_calls_the_model(tmp_path: Path) -> None:
    backend = _Backend(StructuredAnswer("yes", 0.9))
    engine, database, _ticks = _engine(tmp_path, backend, budget=0)
    assert (await engine.resolve("sample", {"n": 1})).path == "fallback"
    assert backend.calls == 0
    database.close()


async def test_obvious_address_stays_on_the_rule(tmp_path: Path) -> None:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    registry = DecisionRegistry()
    for decision in builtin_decisions():
        registry.register(decision)
    backend = _Backend(StructuredAnswer("ignore", 0.99))
    engine = DecisionEngine(registry, backend, database)
    clear = await engine.resolve(
        "addressed_to_bot",
        {"text": "hey Maria", "bot_name": "Maria"},
    )
    assert clear.path == "rules"
    assert clear.value == "respond"
    assert backend.calls == 0
    vague = await engine.resolve(
        "addressed_to_bot",
        {"text": "faut que Maria dorme", "bot_name": "Maria"},
    )
    assert vague.path == "model"
    assert vague.value == "ignore"
    address = next(item for item in builtin_decisions() if item.name == "addressed_to_bot")
    assert address.fallback == "ignore"
    names = [item.name for item in builtin_decisions()]
    assert len(names) == len(set(names)) == 12
    database.close()


def test_catalog_values_match_the_question_vocabulary() -> None:
    for decision in builtin_decisions():
        question = decision.question
        assert question is not None
        if question.kind == "noul":
            assert isinstance(decision.fallback, bool), decision.name
        else:
            assert decision.fallback in question.criteria, decision.name


def test_noul_confidence_follows_the_chosen_side() -> None:
    question = Question(instructions="Vrai ?", criteria={"true": "oui"}, kind="noul")
    likely = SimpleNamespace(nouls={"answer": SimpleNamespace(noul=0.9)})
    unlikely = SimpleNamespace(nouls={"answer": SimpleNamespace(noul=0.1)})
    assert read_answer(likely, question) == StructuredAnswer(True, 0.9)
    no = read_answer(unlikely, question)
    assert no is not None
    assert no.value is False
    assert no.confidence == pytest.approx(0.9)


async def test_concurrent_calls_cannot_overspend_the_budget(tmp_path: Path) -> None:
    backend = _SlowBackend(StructuredAnswer("yes", 0.9))
    engine, database, _ticks = _engine(tmp_path, backend, budget=1)  # type: ignore[arg-type]
    verdicts = await asyncio.gather(
        engine.resolve("sample", {"n": 1}),
        engine.resolve("sample", {"n": 2}),
        engine.resolve("sample", {"n": 3}),
    )
    assert sorted(item.path for item in verdicts) == ["fallback", "fallback", "model"]
    assert backend.calls == 1
    database.close()


class _SlowBackend(_Backend):
    async def ask(self, state: dict[str, object], question: Question) -> StructuredAnswer | None:
        await asyncio.sleep(0.01)
        return await super().ask(state, question)


async def test_missing_jev_key_does_not_call_out() -> None:
    backend = JevBackend("")
    answer = await backend.ask(
        {"text": "salut"},
        Question(instructions="Test.", criteria={"yes": "oui"}),
    )
    assert answer is None
    await backend.close()
