"""Calculs et conversions exacts : l'outil, le repérage de la demande, l'annonce d'un outil lent."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from maria_core.capabilities import Capability, CapabilityRegistry, Context, Result, Risk
from maria_core.capabilities.builtin.calculate import calculate_capability
from maria_core.conversation.calc import needs_calculation
from maria_core.conversation.progress import progress_label
from maria_core.discord.waiting import SlowToolNotice
from maria_core.llm.loop import complete_turn
from maria_core.llm.schema import openai_tool
from maria_core.llm.types import Completion, ToolCall
from tests.fakes import ScriptedClient
from tests.test_service import _message, _open


def _context() -> Context:
    return Context(
        user_id=7,
        guild_id=5,
        channel_id=3,
        message_id=1,
        is_owner=False,
        is_moderator=False,
        text="",
    )


async def _calc(**arguments: Any) -> Result:
    return await calculate_capability().run(_context(), arguments)


def test_the_tool_has_a_valid_strict_schema() -> None:
    schema = openai_tool(calculate_capability())["function"]["parameters"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


async def test_calculations_are_exact_and_unsafe_ones_refused() -> None:
    assert (await _calc(expression="0.2*150")).data["result"] == "30"
    assert (await _calc(expression="(12+8)/3")).data["result"] == "6.666666667"
    assert (await _calc(expression="2^10")).data["result"] == "1024"
    assert (await _calc(expression="sqrt(144)")).data["result"] == "12"
    for bad in ("1/0", "__import__('os')", "9^999", "abc"):
        assert not (await _calc(expression=bad)).ok


async def test_unit_conversions_cover_everyday_units_and_refuse_mixed_ones() -> None:
    km = await _calc(value=42, from_unit="km", to_unit="miles")
    assert km.data["result"] == "26.09759007"
    assert (await _calc(value=100, from_unit="°C", to_unit="fahrenheit")).data["result"] == "212"
    assert (await _calc(value=90, from_unit="km/h", to_unit="m/s")).data["result"] == "25"
    assert (await _calc(value=3, from_unit="kilos", to_unit="livres")).data[
        "result"
    ] == "6.613867866"
    assert (await _calc(value=2, from_unit="heures", to_unit="min")).data["result"] == "120"
    assert (await _calc(value=2, from_unit="Go", to_unit="Mo")).data["result"] == "2000"
    mixed = await _calc(value=1, from_unit="kg", to_unit="m")
    assert not mixed.ok and "impossible" in mixed.error
    assert not (await _calc()).ok


def test_a_calculation_request_is_spotted_but_not_dates_or_currencies() -> None:
    for yes in (
        "combien font 12 x 8",
        "12" + chr(0xD7) + "8",
        "convertis 42 km en miles",
        "20% de 150",
        "5+7",
        "racine carrée de 144",
        "quelle est la moyenne de 12, 15 et 9",
    ):
        assert needs_calculation(yes), yes
    for no in (
        "on se voit le 12/10 à 20h",
        "100 euros en dollars",
        "j'ai 3 chats",
        "15 km à pied",
        "bonjour",
        "calcule ça",
    ):
        assert not needs_calculation(no), no


async def test_a_calculation_forces_the_tool_with_a_hint(tmp_path: Path) -> None:
    registry = CapabilityRegistry()
    registry.register(calculate_capability())
    client = ScriptedClient([Completion(text="Cela fait 96.", model="fake")])
    service, database = _open(tmp_path, client, capabilities=registry)
    await service.handle(_message(mentioned=True, text="combien font 12 x 8"))
    assert client.choices[0] == "required"
    assert any("[CALCUL]" in str(item["content"]) for item in client.seen[0])
    plain = ScriptedClient([Completion(text="Salut.", model="fake")])
    other, other_database = _open(tmp_path / "x", plain, capabilities=registry)
    await other.handle(_message(mentioned=True, text="salut, ça va ?"))
    assert plain.choices[0] == "auto"
    database.close()
    other_database.close()


def test_each_tool_has_a_plain_waiting_sentence() -> None:
    assert progress_label(["search_web"]) == "Je cherche sur le web…"
    assert progress_label(["inconnu", "get_weather"]) == "Je consulte la météo…"
    assert progress_label(["inconnu"]) == "Je m'en occupe…"


async def test_the_waiting_notice_lasts_the_whole_turn_but_only_with_tools() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def waiting(names: Any) -> Any:
        events.append(f"start {list(names)}")
        yield
        events.append("stop")

    async def execute(call: ToolCall) -> Result:
        events.append("tool")
        return Result(ok=True, data={})

    tools = [openai_tool(_echo())]
    with_tool = ScriptedClient(
        [
            Completion(text="", tool_calls=(ToolCall("c1", "echo", {}),), model="fake"),
            Completion(text="voilà", model="fake"),
        ]
    )
    result = await complete_turn(
        with_tool, [], system="s", tools=tools, execute=execute, waiting=waiting
    )
    assert result.text == "voilà"
    assert events == ["start ['echo']", "tool", "stop"]
    events.clear()
    without = ScriptedClient([Completion(text="direct", model="fake")])
    await complete_turn(without, [], system="s", tools=tools, execute=execute, waiting=waiting)
    assert events == []


def _echo() -> Capability:
    async def run(_context: Context, _arguments: Any) -> Result:
        return Result(ok=True, data={})

    return Capability(
        name="echo",
        description="écho",
        parameters={"type": "object", "properties": {}},
        risk=Risk.READ,
        run=run,
    )


class _Sent:
    def __init__(self) -> None:
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


class _Channel:
    def __init__(self) -> None:
        self.sent: list[tuple[str, _Sent]] = []

    async def send(self, content: str, **_options: Any) -> _Sent:
        item = _Sent()
        self.sent.append((content, item))
        return item


class _Message:
    def __init__(self) -> None:
        self.channel = _Channel()


@pytest.mark.parametrize(("work", "expected"), [(0.0, 0), (0.15, 1)])
async def test_the_notice_only_appears_for_a_slow_tool_and_is_removed_after(
    work: float, expected: int
) -> None:
    message = _Message()
    async with SlowToolNotice(message, "Je cherche sur le web…", delay=0.05):  # type: ignore[arg-type]
        await asyncio.sleep(work)
    await asyncio.sleep(0.02)
    assert len(message.channel.sent) == expected
    for content, sent in message.channel.sent:
        assert content == "-# Je cherche sur le web…" and sent.deleted
