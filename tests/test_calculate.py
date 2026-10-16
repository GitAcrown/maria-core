"""Calculs et conversions exacts : l'outil, le repérage de la demande, l'annonce d'un outil lent."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from maria_core.capabilities import Capability, CapabilityRegistry, Context, Result, Risk
from maria_core.capabilities.builtin.calculate import calculate_capability
from maria_core.conversation import progress
from maria_core.conversation.calc import needs_calculation
from maria_core.conversation.progress import progress_label
from maria_core.discord.waiting import SlowNotice
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


def _call(name: str, **arguments: Any) -> ToolCall:
    return ToolCall("c", name, arguments)


def test_each_tool_has_several_waiting_sentences_and_never_repeats_the_last() -> None:
    assert progress_label([_call("search_web")]) in progress._LABELS["search_web"]
    assert (
        progress_label([_call("inconnu"), _call("get_weather")])
        in (progress._LABELS["get_weather"])
    )
    assert progress_label([_call("inconnu")]) in progress._DEFAULT
    assert all(len(options) >= 3 for options in progress._LABELS.values())
    assert all(len(templates) >= 3 for _keys, templates in progress._DETAILED.values())
    last = ""
    for _ in range(60):  # deux recherches de suite : la phrase change à chaque fois
        phrase = progress_label([_call("search_web", query="météo")], last)
        assert phrase != last
        last = phrase
    assert len({progress_label([_call("calculate")]) for _ in range(60)}) == 3


def test_the_waiting_sentence_names_the_search_the_site_or_the_city() -> None:
    def seen(call: ToolCall) -> set[str]:
        return {progress_label([call]) for _ in range(80)}

    search = seen(_call("search_web", query="extrait de naissance en ligne"))
    assert "Je cherche « extrait de naissance en ligne »…" in search
    assert all("extrait de naissance en ligne" in phrase for phrase in search)
    url = "https://www.service-public.fr/particuliers/vosdroits"
    assert seen(_call("read_web_page", url=url)) == {
        "Je lis service-public.fr…",
        "J'ouvre service-public.fr…",
        "Lecture de service-public.fr…",
    }
    assert all("Lyon" in phrase for phrase in seen(_call("get_weather", city="Lyon")))
    # plusieurs appels, ou rien à citer : la phrase générale
    two = [_call("search_web", query="a"), _call("search_web", query="b")]
    assert progress_label(two) in progress._LABELS["search_web"]
    assert progress_label([_call("search_web", query="  ")]) in progress._LABELS["search_web"]


def test_what_is_quoted_is_cleaned_and_short() -> None:
    query = "**gras** [lien](http://x) @everyone `code` ligne " + "mot " * 30
    phrase = progress_label([_call("search_web", query=query)])
    assert not any(char in phrase for char in "*[]()@`")
    assert len(phrase) < 90 and "…" in phrase


async def test_the_loop_announces_each_batch_of_tools_and_nothing_without_tools() -> None:
    told: list[list[str]] = []

    async def announce(calls: Any) -> None:
        told.append([call.name for call in calls])

    async def execute(call: ToolCall) -> Result:
        return Result(ok=True, data={})

    tools = [openai_tool(_echo())]
    with_tool = ScriptedClient(
        [
            Completion(text="", tool_calls=(ToolCall("c1", "echo", {}),), model="fake"),
            Completion(text="", tool_calls=(ToolCall("c2", "echo", {}),), model="fake"),
            Completion(text="voilà", model="fake"),
        ]
    )
    result = await complete_turn(
        with_tool, [], system="s", tools=tools, execute=execute, announce=announce
    )
    assert result.text == "voilà" and told == [["echo"], ["echo"]]
    told.clear()
    without = ScriptedClient([Completion(text="direct", model="fake")])
    await complete_turn(without, [], system="s", tools=tools, execute=execute, announce=announce)
    assert told == []


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
    def __init__(self, content: str) -> None:
        self.id = 900
        self.content = content
        self.deleted = False

    async def edit(self, *, content: str) -> None:
        self.content = content

    async def delete(self) -> None:
        self.deleted = True


class _Channel:
    def __init__(self, last_message_id: int) -> None:
        self.last_message_id = last_message_id
        self.sent: list[_Sent] = []
        self.references: list[object] = []

    async def send(self, content: str, **options: Any) -> _Sent:
        item = _Sent(content)
        self.sent.append(item)
        self.references.append(options.get("reference"))
        return item


class _Message:
    def __init__(self, last_message_id: int = 1) -> None:
        self.id = 1
        self.channel = _Channel(last_message_id)


@pytest.mark.parametrize(("work", "expected"), [(0.0, 0), (0.15, 1)])
async def test_the_notice_only_appears_when_the_answer_is_slow_and_is_removed_after(
    work: float, expected: int
) -> None:
    message = _Message()
    async with SlowNotice(message, delay=0.05):  # type: ignore[arg-type]
        await asyncio.sleep(work)
    await asyncio.sleep(0.02)
    assert len(message.channel.sent) == expected
    for sent in message.channel.sent:
        assert sent.content.startswith("-# Je ") and sent.deleted


async def test_the_notice_changes_its_sentence_when_a_tool_starts() -> None:
    message = _Message()
    async with SlowNotice(message, delay=0.03) as notice:  # type: ignore[arg-type]
        await notice.say("Je lis la page…")  # avant l'envoi : sert de première phrase
        await asyncio.sleep(0.08)
        assert message.channel.sent[0].content == "-# Je lis la page…"
        await notice.say("Je calcule…")  # après l'envoi : le message est modifié
        assert message.channel.sent[0].content == "-# Je calcule…"
    assert message.channel.sent[0].deleted


async def test_the_notice_replies_only_when_other_messages_came_after() -> None:
    last, later = _Message(last_message_id=1), _Message(last_message_id=2)
    for message in (last, later):
        async with SlowNotice(message, delay=0.01):  # type: ignore[arg-type]
            await asyncio.sleep(0.05)
    assert last.channel.references == [None]
    assert later.channel.references == [later]


class _Recorder:
    def __init__(self) -> None:
        self.said: list[str] = []
        self.entered = 0

    async def __aenter__(self) -> "_Recorder":
        self.entered += 1
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def say(self, label: str) -> None:
        self.said.append(label)


async def test_the_service_gives_the_notice_the_tool_sentence(tmp_path: Path) -> None:
    registry = CapabilityRegistry()
    registry.register(calculate_capability())
    client = ScriptedClient(
        [
            Completion(
                text="",
                tool_calls=(ToolCall("c1", "calculate", {"expression": "1+1"}),),
                model="fake",
            ),
            Completion(text="2.", model="fake"),
        ]
    )
    service, database = _open(tmp_path, client, capabilities=registry)
    notice = _Recorder()
    await service.handle(_message(mentioned=True, text="1+1"), waiting=lambda: notice)
    assert notice.entered == 1 and len(notice.said) == 1
    assert notice.said[0] in progress._LABELS["calculate"]
    database.close()


async def test_no_notice_when_the_answer_may_be_silence(tmp_path: Path) -> None:
    client = ScriptedClient([Completion(text="[[SILENCE]]", model="fake")])
    service, database = _open(tmp_path, client)
    notice = _Recorder()
    message = _message(mentioned=False, text="Maria", author_is_bot=False)
    await service.handle(message, waiting=lambda: notice)
    assert client.seen and notice.entered == 0  # le modèle a bien été appelé
    database.close()


async def test_two_tool_batches_change_the_sentence_and_chat_never_opens_a_notice(
    tmp_path: Path,
) -> None:
    registry = CapabilityRegistry()
    registry.register(calculate_capability())
    call = ToolCall("c1", "calculate", {"expression": "1+1"})
    client = ScriptedClient(
        [
            Completion(text="", tool_calls=(call,), model="fake"),
            Completion(
                text="",
                tool_calls=(ToolCall("c2", "calculate", {"expression": "2+2"}),),
                model="fake",
            ),
            Completion(text="4.", model="fake"),
        ]
    )
    service, database = _open(tmp_path, client, capabilities=registry)
    notice = _Recorder()
    await service.handle(_message(mentioned=True, text="1+1 puis 2+2"), waiting=lambda: notice)
    assert notice.entered == 1  # une seule annonce, modifiée d'un lot au suivant
    assert len(notice.said) == 2 and notice.said[0] != notice.said[1]
    chat = ScriptedClient([Completion(text="Salut !", model="fake")])
    other, other_database = _open(tmp_path / "chat", chat)
    quiet = _Recorder()
    await other.handle(_message(mentioned=True, text="salut, ça va ?"), waiting=lambda: quiet)
    assert quiet.entered == 0 and quiet.said == []
    database.close()
    other_database.close()
