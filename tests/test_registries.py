"""Catalogues : noms, familles, ordre du prompt, immuabilité d'un résultat."""

from collections.abc import Mapping
from typing import Any

import pytest

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.decisions import Decision
from maria_core.decisions.catalog import builtin_decisions
from maria_core.decisions.rules import followup_rules
from maria_core.errors import RegistryError
from maria_core.llm import PromptSections
from maria_core.objectives import ObjectiveKind, ObjectiveTypes
from maria_core.social.levels import LEVELS


async def _run(_ctx: Context, _args: Mapping[str, Any]) -> Result:
    return Result(ok=True, data={"ok": True})


def test_result_data_cannot_be_mutated() -> None:
    result = Result(ok=True, data={"value": 1})
    with pytest.raises(TypeError):
        result.data["value"] = 2  # type: ignore[index]


def test_capability_name_must_be_an_identifier() -> None:
    with pytest.raises(RegistryError, match="Capacité"):
        Capability(
            name="Sample Tool",
            description="Non",
            parameters={},
            risk=Risk.READ,
            run=_run,
        )


def test_context_rejects_a_boolean_identifier() -> None:
    with pytest.raises(RegistryError, match="user_id"):
        Context(
            user_id=True,  # type: ignore[arg-type]
            guild_id=None,
            channel_id=1,
            message_id=None,
            is_owner=False,
            is_moderator=False,
            text="",
        )


def test_prompt_sections_follow_order_and_skip_blanks() -> None:
    sections = PromptSections()
    sections.register_section("late", lambda: "B", order=20)
    sections.register_section("early", lambda: "A", order=10)
    sections.register_section("empty", lambda: "  ", order=5)
    assert sections.render() == "A\n\nB"


def test_volatile_sections_stay_out_of_the_cached_prompt() -> None:
    sections = PromptSections()
    sections.register_section("fixed", lambda: "A", order=1)
    sections.register_section("clock", lambda: "12:00", order=2, volatile=True)
    assert sections.render() == "A"
    assert sections.render_volatile() == "12:00"


def test_objective_kind_must_match_its_family() -> None:
    types = ObjectiveTypes()
    trigger = ObjectiveKind(name="at", family="trigger", description="Échéance")
    types.register_trigger(trigger)
    with pytest.raises(RegistryError, match="famille"):
        types.register_condition(trigger)
    assert types.names("trigger") == ("at",)


def test_decision_threshold_stays_between_zero_and_one() -> None:
    with pytest.raises(RegistryError, match="seuil"):
        Decision(name="addressed_to_bot", threshold=1.5, fallback=False)
    decision = Decision(name="addressed_to_bot", threshold=0.65, fallback=False)
    assert decision.fallback is False


def test_a_followup_is_caught_a_little_more_readily() -> None:
    followup = next(item for item in builtin_decisions() if item.name == "followup")
    assert followup.threshold == 0.5
    assert LEVELS["normal"].followup_s == 24.0 and LEVELS["normal"].followup_depth == 0
    assert followup_rules({"question": True, "depth": 0, "elapsed_s": 10, "same_author": True})
    assert followup_rules({"question": True, "depth": 1, "elapsed_s": 10}) is None
    hit = followup_rules({"question": True, "depth": 4, "elapsed_s": 10})
    assert hit is not None and hit.value == "ignore"
