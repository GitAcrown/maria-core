"""Le service répond, se tait, transcrit, et rejoue une édition."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maria_core.capabilities import Capability, CapabilityRegistry, Context, Result, Risk
from maria_core.config import Settings
from maria_core.conversation.model import AudioRef, Inbound
from maria_core.conversation.persona import clock_section
from maria_core.conversation.service import UNAVAILABLE_TEXT, ConversationService
from maria_core.db import Database
from maria_core.decisions.engine import Decider
from maria_core.decisions.types import Verdict
from maria_core.llm.prompt import PromptSections
from maria_core.llm.types import Completion, ToolCall
from maria_core.ui.widgets import WidgetRegistry
from tests.fakes import ScriptedClient


def _open(
    tmp_path: Path,
    client: ScriptedClient,
    engine: Decider | None = None,
    debounce_seconds: float = 0,
    capabilities: CapabilityRegistry | None = None,
    widgets: WidgetRegistry | None = None,
) -> tuple[ConversationService, Database]:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    prompt = PromptSections()
    prompt.register_section("personality", lambda: "Tu es MARIA.", order=0)
    service = ConversationService(
        database=database,
        client=client,
        capabilities=capabilities or CapabilityRegistry(),
        prompt=prompt,
        settings=Settings.for_tests(tmp_path / "data"),
        debounce_seconds=debounce_seconds,
        engine=engine,
        widgets=widgets,
    )
    return service, database


def _message(**overrides: object) -> Inbound:
    values: dict[str, object] = {
        "channel_id": 1,
        "message_id": 10,
        "guild_id": 5,
        "author_id": 7,
        "author_name": "Léa",
        "text": "salut",
        "is_dm": False,
        "author_is_bot": False,
        "mentioned": False,
        "reply_to_bot": False,
        "mention_everyone": False,
        "edited": False,
        "author_is_owner": False,
        "author_is_moderator": False,
        "bot_names": ("Maria",),
    }
    values.update(overrides)
    return Inbound(**values)  # type: ignore[arg-type]


async def test_unaddressed_message_does_not_call_the_model(tmp_path: Path) -> None:
    client = ScriptedClient([])
    service, database = _open(tmp_path, client)
    assert await service.handle(_message()) is None
    assert client.seen == []
    database.close()


async def test_mention_returns_the_model_text_and_logs_the_call(tmp_path: Path) -> None:
    client = ScriptedClient(
        [Completion(text="coucou", model="fake", input_tokens=3, output_tokens=1)]
    )
    service, database = _open(tmp_path, client)
    reply = await service.handle(_message(mentioned=True, text="Maria ?"))
    assert reply is not None
    assert reply.chunks == ("coucou",)
    assert reply.reply is True
    row = database.fetchone("SELECT model, input_tokens, ok FROM llm_calls")
    assert row is not None
    assert row["model"] == "fake"
    assert row["ok"] == 1
    database.close()


async def test_blank_answer_is_not_sent(tmp_path: Path) -> None:
    client = ScriptedClient([Completion(text="   ", model="fake")])
    service, database = _open(tmp_path, client)
    assert await service.handle(_message(mentioned=True, text="salut")) is None
    database.close()


async def _load_audio() -> bytes:
    return b"audio"


async def test_a_direct_message_does_not_call_the_model(tmp_path: Path) -> None:
    client = ScriptedClient([Completion(text="coucou", model="fake")])
    service, database = _open(tmp_path, client)
    reply = await service.handle(
        _message(
            is_dm=True,
            guild_id=None,
            text="salut",
            audio=AudioRef(filename="voice.ogg", size=5, load=_load_audio),
        )
    )
    assert reply is None
    assert client.seen == []
    database.close()


async def test_voice_is_transcribed_when_addressed(tmp_path: Path) -> None:
    client = ScriptedClient([Completion(text="entendu", model="fake")], transcript="il fait beau")
    service, database = _open(tmp_path, client)
    voice = _message(
        mentioned=True,
        text="",
        audio=AudioRef(filename="voice.ogg", size=5, load=_load_audio),
    )
    transcript = await service.transcribe(voice.audio)
    assert transcript == "il fait beau"
    reply = await service.handle(voice.with_text(transcript, transcribed=True))
    assert reply is not None
    assert reply.chunks == ("entendu",)
    assert "il fait beau" in str(client.seen[0])
    database.close()


async def test_edit_replaces_the_previous_reply(tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            Completion(text="première", model="fake"),
            Completion(text="deuxième", model="fake"),
        ]
    )
    service, database = _open(tmp_path, client)
    first = await service.handle(_message(mentioned=True, message_id=4, text="Maria"))
    assert first is not None
    service.remember_reply(4, 99)
    second = await service.handle(
        _message(mentioned=True, message_id=4, text="Maria corrigée", edited=True)
    )
    assert second is not None
    assert second.chunks == ("deuxième",)
    assert second.edit_message_id == 99
    assert second.reply is False
    database.close()


async def test_burst_keeps_every_message_and_answers_the_last(tmp_path: Path) -> None:
    client = ScriptedClient([Completion(text="les deux", model="fake")])
    service, database = _open(tmp_path, client, debounce_seconds=0.05)
    first, second = await asyncio.gather(
        service.handle(_message(mentioned=True, message_id=1, text="un")),
        service.handle(_message(mentioned=True, message_id=2, text="deux")),
    )
    replies = [item for item in (first, second) if item is not None]
    assert len(replies) == 1
    assert replies[0].user_message_id == 2
    sent = str(client.seen[0])
    assert ": un" in sent
    assert ": deux" in sent
    database.close()


async def test_model_failure_sends_a_notice_kept_out_of_history(tmp_path: Path) -> None:
    client = ScriptedClient([Completion(text="revenue", model="fake")])
    client.fail = True
    service, database = _open(tmp_path, client)
    reply = await service.handle(_message(mentioned=True, message_id=1))
    assert reply is not None
    assert reply.chunks == (UNAVAILABLE_TEXT,)
    client.fail = False
    await service.handle(_message(mentioned=True, message_id=2, text="encore"))
    assert UNAVAILABLE_TEXT not in str(client.seen[-1])
    row = database.fetchone("SELECT ok FROM llm_calls ORDER BY id LIMIT 1")
    assert row is not None
    assert row["ok"] == 0
    database.close()


async def test_edit_of_an_unknown_message_is_ignored(tmp_path: Path) -> None:
    client = ScriptedClient([Completion(text="non", model="fake")])
    service, database = _open(tmp_path, client)
    edited = _message(mentioned=True, message_id=77, text="Maria ?", edited=True)
    assert await service.handle(edited) is None
    assert client.seen == []
    database.close()


async def test_thinking_wraps_the_model_call(tmp_path: Path) -> None:
    client = ScriptedClient([Completion(text="ok", model="fake")])
    service, database = _open(tmp_path, client)
    events: list[str] = []

    @asynccontextmanager
    async def thinking() -> AsyncIterator[None]:
        events.append("start")
        yield
        events.append("stop")

    await service.handle(_message(mentioned=True), thinking=thinking)
    assert events == ["start", "stop"]
    assert await service.handle(_message(), thinking=thinking) is None
    assert events == ["start", "stop"]
    database.close()


async def _card(_context: Context, _args: Mapping[str, Any]) -> Result:
    return Result(ok=True, data={"n": 1}, widget="card")


async def test_widget_text_is_appended_to_the_reply(tmp_path: Path) -> None:
    capabilities = CapabilityRegistry()
    widgets = WidgetRegistry()
    capabilities.register(
        Capability(
            name="card_tool",
            description="Carte",
            parameters={"type": "object", "properties": {}, "required": []},
            risk=Risk.READ,
            run=_card,
        )
    )
    widgets.register("card", lambda data: f"carte {data['n']}")
    client = ScriptedClient(
        [
            Completion(
                text="",
                tool_calls=(ToolCall(id="1", name="card_tool", arguments={}),),
                model="fake",
            ),
            Completion(text="voilà", model="fake"),
        ]
    )
    service, database = _open(tmp_path, client, capabilities=capabilities, widgets=widgets)
    reply = await service.handle(_message(mentioned=True, text="montre"))
    assert reply is not None
    assert "voilà" in reply.chunks[0]
    assert "carte 1" in reply.chunks[0]
    database.close()


def test_clock_section_uses_paris_time() -> None:
    render = clock_section(lambda: datetime(2026, 10, 11, 12, 5, tzinfo=UTC))
    assert render() == "Nous sommes le dimanche 11 octobre 2026, 14:05 à Paris."


class _VerdictEngine:
    def __init__(self, value: str) -> None:
        self.value = value
        self.calls = 0
        self.names: list[str] = []

    async def resolve(self, name: str, state: dict[str, object]) -> Verdict:
        self.calls += 1
        self.names.append(name)
        return Verdict(name=name, value=self.value, path="model", confidence=0.9)


async def test_ambiguous_name_follows_the_decision(tmp_path: Path) -> None:
    client = ScriptedClient([Completion(text="je suis là", model="fake")])
    engine = _VerdictEngine("respond")
    service, database = _open(tmp_path, client, engine)
    database.execute(
        """
        INSERT INTO guild_settings (guild_id, mode, updated_at)
        VALUES (5, 'greedy', '2026-10-11T00:00:00+00:00')
        """
    )
    reply = await service.handle(_message(text="faut que Maria range ça"))
    assert engine.names[0] == "addressed_to_bot"
    assert reply is not None
    assert reply.chunks == ("je suis là",)
    database.close()


async def test_ambiguous_name_can_stay_silent(tmp_path: Path) -> None:
    client = ScriptedClient([Completion(text="je suis là", model="fake")])
    engine = _VerdictEngine("ignore")
    service, database = _open(tmp_path, client, engine)
    database.execute(
        """
        INSERT INTO guild_settings (guild_id, mode, updated_at)
        VALUES (5, 'greedy', '2026-10-11T00:00:00+00:00')
        """
    )
    assert await service.handle(_message(text="faut que Maria range ça")) is None
    assert engine.calls == 1
    assert client.seen == []
    database.close()
