"""Un outil en panne : nouvel essai si c'est passager, consigne honnête, jamais de silence."""

import json
from typing import Any

from maria_core.capabilities import Result
from maria_core.conversation.compose import compose
from maria_core.llm.loop import LoopResult, ToolRecord, complete_turn, is_transient
from maria_core.llm.types import Completion, ToolCall
from maria_core.ui.widgets import WidgetRegistry
from tests.fakes import ScriptedClient


def _calls(name: str) -> list[Completion]:
    call = ToolCall("c1", name, {})
    return [
        Completion(text="", tool_calls=(call,), model="fake"),
        Completion(text="Voilà.", model="fake"),
    ]


def test_only_passing_failures_are_called_transient() -> None:
    for error in ("Délai dépassé.", "Connection timed out", "Service indisponible", "HTTP 503"):
        assert is_transient(error), error
    for error in ("Ville introuvable.", "Une recherche suffit", "Valeur vide."):
        assert not is_transient(error), error


async def test_a_reading_tool_is_retried_once_when_the_failure_is_passing() -> None:
    attempts: list[int] = []

    async def execute(call: ToolCall) -> Result:
        attempts.append(1)
        if len(attempts) == 1:
            return Result(ok=False, data={}, error="Délai dépassé.")
        return Result(ok=True, data={"temp": 12})

    result = await complete_turn(
        ScriptedClient(_calls("get_weather")),
        [],
        system="s",
        tools=[{"type": "function"}],
        execute=execute,
        parallel_safe=lambda name: name == "get_weather",
    )
    assert len(attempts) == 2 and result.records[0].result.ok


async def test_a_writing_tool_or_a_lasting_failure_is_never_retried() -> None:
    attempts: list[int] = []

    async def failing(call: ToolCall) -> Result:
        attempts.append(1)
        return Result(ok=False, data={}, error="Délai dépassé.")

    await complete_turn(
        ScriptedClient(_calls("objective_create")),
        [],
        system="s",
        tools=[{"type": "function"}],
        execute=failing,
        parallel_safe=lambda _name: False,
    )
    assert len(attempts) == 1  # une écriture ne se rejoue pas : elle pourrait doubler

    attempts.clear()

    async def unknown(call: ToolCall) -> Result:
        attempts.append(1)
        return Result(ok=False, data={}, error="Ville introuvable.")

    await complete_turn(
        ScriptedClient(_calls("get_weather")),
        [],
        system="s",
        tools=[{"type": "function"}],
        execute=unknown,
        parallel_safe=lambda _name: True,
    )
    assert len(attempts) == 1


async def test_a_service_that_stays_down_comes_with_an_honest_instruction() -> None:
    async def execute(call: ToolCall) -> Result:
        return Result(ok=False, data={}, error="Délai dépassé.")

    client = ScriptedClient(_calls("search_web"))
    await complete_turn(
        client,
        [],
        system="s",
        tools=[{"type": "function"}],
        execute=execute,
        parallel_safe=lambda _name: True,
    )
    tool_message: dict[str, Any] = next(
        message for message in client.seen[1] if message.get("role") == "tool"
    )
    payload = json.loads(str(tool_message["content"]))
    assert payload["ok"] is False and "n'invente jamais" in payload["consigne"].lower()


def _outcome(text: str, *records: ToolRecord) -> LoopResult:
    return LoopResult(text, tuple(r.name for r in records), 1, 0, 0, "m", 0, True, records=records)


def test_when_every_tool_failed_and_the_model_said_nothing_the_reply_says_what_failed() -> None:
    failed = ToolRecord("get_weather", {}, Result(ok=False, data={}, error="Délai dépassé."))
    composed = compose(_outcome("", failed), WidgetRegistry(), ("maria",))
    assert "la météo" in composed.text and "Réessaie" in composed.text
    two = compose(
        _outcome(
            "",
            failed,
            ToolRecord("search_web", {}, Result(ok=False, data={}, error="x")),
        ),
        WidgetRegistry(),
        ("maria",),
    )
    assert "la météo ni la recherche web" in two.text


def test_the_model_own_words_and_partial_successes_are_left_alone() -> None:
    failed = ToolRecord("get_weather", {}, Result(ok=False, data={}, error="Délai dépassé."))
    worked = ToolRecord("search_web", {}, Result(ok=True, data={"results": []}))
    assert compose(_outcome("La météo ne répond pas.", failed), WidgetRegistry(), ("m",)).text == (
        "La météo ne répond pas."
    )
    assert compose(_outcome("", failed, worked), WidgetRegistry(), ("m",)).text == ""
