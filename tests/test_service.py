"""Le service répond, se tait, transcrit, et rejoue une édition."""

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maria_core.attachments import Digester
from maria_core.capabilities import Capability, CapabilityRegistry, Context, Result, Risk
from maria_core.capabilities.page import Fetched
from maria_core.config import Settings
from maria_core.conversation.model import AudioRef, FileRef, Inbound
from maria_core.conversation.persona import clock_section
from maria_core.conversation.pressure import Pressure
from maria_core.conversation.service import UNAVAILABLE_TEXT, ConversationService
from maria_core.db import Database
from maria_core.decisions.engine import Decider
from maria_core.decisions.rules import claim_rules
from maria_core.decisions.types import Verdict
from maria_core.llm.prompt import PromptSections
from maria_core.llm.types import Completion, ToolCall
from maria_core.profile import Profiles
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


class _Verifier:
    """`intent` : chat. `claim_check` : ce qu'on lui a dit de répondre."""

    def __init__(self, claim: str) -> None:
        self.claim = claim
        self.asked: list[str] = []

    async def resolve(self, name: str, state: Mapping[str, Any]) -> Verdict:
        self.asked.append(name)
        value = self.claim if name == "claim_check" else "none"
        return Verdict(name=name, value=value, path="model", confidence=0.9)


def _lookup(calls: list[str]) -> CapabilityRegistry:
    async def run(_context: Context, _args: Mapping[str, Any]) -> Result:
        calls.append("search")
        return Result(ok=True, data={"results": [{"title": "Le PSG a gagné 2-1"}]})

    registry = CapabilityRegistry()
    registry.register(
        Capability(
            name="search_web",
            description="Cherche",
            parameters={"type": "object", "properties": {}, "required": []},
            risk=Risk.READ,
            run=run,
        )
    )
    return registry


async def test_a_live_fact_given_without_a_tool_is_checked_once(tmp_path: Path) -> None:
    calls: list[str] = []
    client = ScriptedClient(
        [
            Completion(text="Le PSG a gagné 3-0 hier soir.", model="fake", input_tokens=5),
            Completion(
                text="",
                tool_calls=(ToolCall(id="1", name="search_web", arguments={}),),
                model="fake",
                input_tokens=7,
            ),
            Completion(text="Le PSG a gagné 2-1 hier soir.", model="fake", input_tokens=2),
        ]
    )
    engine = _Verifier("needs_check")
    service, database = _open(tmp_path, client, engine=engine, capabilities=_lookup(calls))
    reply = await service.handle(_message(mentioned=True, text="Maria, le PSG a fait quoi hier ?"))
    assert reply is not None and reply.chunks == ("Le PSG a gagné 2-1 hier soir.",)
    assert calls == ["search"]
    assert client.choices[1] == "required"
    row = database.fetchone("SELECT input_tokens FROM llm_calls")
    assert row is not None and row["input_tokens"] == 14  # les deux essais sont comptés
    database.close()


async def test_chat_and_grounded_answers_are_left_alone(tmp_path: Path) -> None:
    calls: list[str] = []
    client = ScriptedClient([Completion(text="Le PSG a gagné 3-0 hier soir.", model="fake")])
    service, database = _open(
        tmp_path, client, engine=_Verifier("grounded"), capabilities=_lookup(calls)
    )
    reply = await service.handle(_message(mentioned=True, text="Maria, le PSG a fait quoi hier ?"))
    assert reply is not None and reply.chunks == ("Le PSG a gagné 3-0 hier soir.",)
    assert calls == [] and len(client.seen) == 1
    database.close()


def test_only_answers_with_checkable_facts_reach_the_decision() -> None:
    assert claim_rules({"answer": "Salut, ça va bien et toi ?"}).value == "grounded"
    assert claim_rules({"answer": "Le PSG a gagné 3-0 hier soir.", "tools": 1}).value == "grounded"
    assert claim_rules({"answer": "Oui."}).value == "grounded"
    assert claim_rules({"answer": "Il fait très beau en ce moment dans le sud."}) is None
    assert claim_rules({"answer": "Le PSG a gagné 3-0 hier soir au Parc des Princes."}) is None


async def test_links_files_and_profile_reach_the_model(tmp_path: Path) -> None:
    async def fetch(url: str) -> Fetched:
        return Fetched(
            b"<html><title>Article</title><p>Texte du lien.</p></html>", "text/html", url
        )

    client = ScriptedClient([Completion(text="Lu.", model="fake")])
    database = Database(tmp_path / "maria.db")
    database.migrate()
    profiles = Profiles(database)
    profiles.store.set(7, "city", "Lyon", datetime(2026, 10, 14, tzinfo=UTC))
    prompt = PromptSections()
    prompt.register_section("personality", lambda: "Tu es MARIA.", order=0)
    service = ConversationService(
        database=database,
        client=client,
        capabilities=CapabilityRegistry(),
        prompt=prompt,
        settings=Settings.for_tests(tmp_path / "data"),
        debounce_seconds=0,
        profiles=profiles,
        sources=(profiles.prompt_for,),
        digester=Digester(fetch),
    )
    video = FileRef(filename="clip.mp4", size=10, load=_load_audio, content_type="video/mp4")
    message = _message(mentioned=True, text="Maria, lis https://exemple.fr/a", files=(video,))
    reply = await service.handle(message)
    assert reply is not None and reply.chunks == ("Lu.",)
    system = " ".join(str(m["content"]) for m in client.seen[0] if m["role"] == "system")
    assert "PROFIL DE Léa" in system and "ville : Lyon" in system
    seen = "\n".join(str(item["content"]) for item in client.seen[0])
    assert "Texte du lien." in seen
    assert "- clip.mp4 : vidéo" in seen
    assert "NON LISIBLE" in seen
    database.close()


def test_talking_to_maria_elsewhere_does_not_close_the_door_here() -> None:
    pressure = Pressure()
    # Léa a une réponse dans le salon 1 ; dans le salon 2 elle n'a écrit qu'un message.
    assert pressure.allow(7, 1, author_pace=1, channel_pace=1)
    assert not pressure.allow(7, 1, author_pace=1, channel_pace=1)
    assert pressure.allow(7, 2, author_pace=1, channel_pace=1)
