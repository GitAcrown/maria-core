"""La boucle s'arrête, rend l'erreur d'un outil, et n'invente pas de texte."""

from collections.abc import Mapping
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.llm.loop import complete_turn
from maria_core.llm.schema import openai_tool
from maria_core.llm.types import Completion, ToolCall
from tests.fakes import ScriptedClient


def _call(index: int) -> Completion:
    return Completion(
        text="",
        tool_calls=(ToolCall(id=f"c{index}", name="echo", arguments={"n": index}),),
        input_tokens=2,
        output_tokens=1,
        model="fake",
    )


async def _run(_context: Context, _arguments: Mapping[str, Any]) -> Result:
    return Result(ok=True, data={"done": True})


async def test_loop_stops_after_four_model_calls() -> None:
    client = ScriptedClient([_call(1), _call(2), _call(3), _call(4)])
    executed: list[str] = []

    async def execute(call: ToolCall) -> Result:
        executed.append(call.id)
        return Result(ok=True, data={})

    result = await complete_turn(
        client,
        [{"role": "user", "content": "bonjour"}],
        system="système",
        tools=[{"type": "function"}],
        execute=execute,
    )
    assert result.calls == 4
    assert executed == ["c1", "c2", "c3"]
    assert client.choices == ["auto", "auto", "auto", "none"]
    assert client.tools[-1] == [{"type": "function"}]
    assert result.text == ""


async def test_tool_error_is_shown_to_the_model() -> None:
    client = ScriptedClient(
        [
            Completion(
                text="",
                tool_calls=(ToolCall(id="boom", name="echo", arguments={}),),
                model="fake",
            ),
            Completion(text="d'accord", model="fake"),
        ]
    )

    async def execute(_call: ToolCall) -> Result:
        raise RuntimeError("casse")

    result = await complete_turn(
        client,
        [{"role": "user", "content": "vas-y"}],
        system="système",
        tools=[{"type": "function"}],
        execute=execute,
    )
    assert result.text == "d'accord"
    tool_messages = [item for item in client.seen[1] if item["role"] == "tool"]
    assert tool_messages
    assert "casse" in str(tool_messages[0]["content"])


async def test_a_turn_stops_at_six_tool_calls() -> None:
    calls = tuple(ToolCall(id=f"c{index}", name="echo", arguments={}) for index in range(7))
    client = ScriptedClient(
        [Completion(text="", tool_calls=calls, model="fake"), Completion(text="stop", model="fake")]
    )
    executed: list[str] = []

    async def execute(call: ToolCall) -> Result:
        executed.append(call.id)
        return Result(ok=True, data={})

    result = await complete_turn(
        client,
        [{"role": "user", "content": "bonjour"}],
        system="système",
        tools=[{"type": "function"}],
        execute=execute,
    )
    assert executed == ["c0", "c1", "c2", "c3", "c4", "c5"]
    assert "Plafond" in str(client.seen[1])
    assert result.text == "stop"


def test_blank_completion_is_empty() -> None:
    assert Completion(text="   ").text.strip() == ""


def test_capability_schema_is_strict() -> None:
    tool = openai_tool(
        Capability(
            name="echo",
            description="Répète",
            parameters={"properties": {"text": {"type": "string"}}},
            risk=Risk.READ,
            run=_run,
        )
    )
    function = tool["function"]
    assert function["strict"] is True
    assert function["parameters"]["additionalProperties"] is False
    assert function["parameters"]["required"] == ["text"]


def test_optional_and_nested_parameters_become_strict() -> None:
    tool = openai_tool(
        Capability(
            name="search",
            description="Cherche",
            parameters={
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "unit": {"type": "string", "enum": ["c", "f"]},
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"site": {"type": "string"}},
                        },
                    },
                },
                "required": ["query", "filters"],
            },
            risk=Risk.READ,
            run=_run,
        )
    )
    parameters = tool["function"]["parameters"]
    properties = parameters["properties"]
    assert parameters["required"] == ["query", "limit", "unit", "filters"]
    assert properties["query"] == {"type": "string"}
    assert properties["limit"] == {"type": ["integer", "null"]}
    assert properties["unit"]["anyOf"][1] == {"type": "null"}
    nested = properties["filters"]["items"]
    assert nested["additionalProperties"] is False
    assert nested["required"] == ["site"]
