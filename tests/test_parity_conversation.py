"""Conversation, spontanéité, mémoire, rendu : ce que la revue de parité a corrigé."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from maria_core.capabilities import Capability, CapabilityRegistry, Result, Risk, Source
from maria_core.capabilities.http import HttpResponse
from maria_core.capabilities.page import fetch_text
from maria_core.config import Settings
from maria_core.conversation.compose import compose
from maria_core.conversation.context import (
    can_stay_silent,
    is_reaction_request,
    reaction_target,
    user_entry,
)
from maria_core.conversation.model import Action, Inbound, Quote, Route
from maria_core.conversation.policy import load_policy, save_transcribe
from maria_core.conversation.service import ConversationService
from maria_core.db import Database
from maria_core.decisions.types import Verdict
from maria_core.discord.inbound import image_url
from maria_core.discord.layout import build_views, quiet_links
from maria_core.llm.clean import clean_reply
from maria_core.llm.history import ChannelHistory
from maria_core.llm.loop import LoopResult, ToolRecord
from maria_core.llm.prompt import PromptSections
from maria_core.llm.types import Completion, ToolCall
from maria_core.memory.policy import Actor
from maria_core.memory.service import Memories
from maria_core.memory.text import about_someone_else, close, second_person
from maria_core.social.service import ReactionSeen, Social
from maria_core.ui.widgets import WidgetRegistry, card, gallery, heading, text
from maria_core.vectors import NullIndex
from tests.fakes import ScriptedClient
from tests.http_fake import FakeHttp

_NOW = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)


def _message(**overrides: object) -> Inbound:
    values: dict[str, object] = {
        "channel_id": 3,
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
        "created_at": _NOW,
    }
    values.update(overrides)
    return Inbound(**values)  # type: ignore[arg-type]


class _Engine:
    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers
        self.names: list[str] = []

    async def resolve(self, name: str, state: dict[str, object]) -> Verdict:
        self.names.append(name)
        return Verdict(name=name, value=self.answers.get(name, False), path="model", confidence=1)


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    return database


def test_a_thread_reads_the_settings_of_its_parent(tmp_path: Path) -> None:
    database = _database(tmp_path)
    save_transcribe(database, 3, 5, True)
    in_thread = _message(channel_id=77, settings_channel_id=3)
    assert load_policy(database, in_thread).auto_transcribe is True
    database.close()


def test_history_tags_context_gaps_and_keeps_images_only_when_addressed() -> None:
    history = ChannelHistory(
        max_messages=20,
        max_tokens=5000,
        max_age=timedelta(days=1),
        clock=lambda: _NOW + timedelta(hours=1),
    )
    pictured = _message(images=(), text="regarde")
    history.add(user_entry(pictured, addressed=False))
    later = _message(message_id=11, created_at=_NOW + timedelta(minutes=45), text="Maria ?")
    history.add(user_entry(later, addressed=True))
    rendered = history.api_messages()
    assert rendered[0]["content"].startswith("[contexte] [")
    assert "pause de 45 min" in rendered[1]["content"]
    assert "Léa (7) : Maria ?" in rendered[2]["content"]


def test_a_quote_is_shown_as_a_citation_and_not_as_the_author_text() -> None:
    quote = Quote(
        message_id=4,
        author_id=8,
        author_name="Noé",
        text="on mange où",
        from_bot_self=False,
        from_bot=False,
    )
    entry = user_entry(_message(text="ici", quote=quote), addressed=True)
    assert "Cité (reply, pas le texte de ce membre) — répond à Noé (8)" in entry.content
    assert reaction_target(_message(text="réagis à son message", quote=quote)) == 4
    assert reaction_target(_message(text="réagis à mon message", quote=quote)) == 10
    assert is_reaction_request("Maria réagis à ça")
    assert not is_reaction_request("les réactions de la foule étaient folles " * 20)


def test_silence_is_only_allowed_for_a_name_without_a_question() -> None:
    named = Route(Action.RESPOND, "name_edge")
    assert can_stay_silent(_message(text="Maria trop bien"), named)
    assert not can_stay_silent(_message(text="Maria ça va ?"), named)
    assert not can_stay_silent(_message(mentioned=True), named)


def test_replies_are_cleaned_and_sources_become_a_discreet_footer() -> None:
    assert clean_reply("[à Léa] Oui [s1], c'est ça.", ("Maria",)) == "Oui, c'est ça."
    assert clean_reply("Maria", ("Maria",)) == ""
    record = ToolRecord(
        "search_web",
        {"query": "maria"},
        Result(
            ok=True,
            data={"results": [{"title": "A", "url": "https://www.news.test/a"}]},
            sources=(Source("A", "https://www.news.test/a"),),
        ),
    )
    outcome = LoopResult(
        text="Voilà.",
        tool_names=("search_web",),
        calls=2,
        input_tokens=0,
        output_tokens=0,
        model="m",
        duration_ms=0,
        ok=True,
        records=(record,),
    )
    composed = compose(outcome, WidgetRegistry(), ("Maria",))
    assert composed.text == "Voilà."
    assert composed.footer == "-# **Source** · [news.test](<https://www.news.test/a>)"
    assert composed.notes and composed.notes[0].startswith("search_web : ")


async def test_a_second_web_search_is_refused_unless_the_first_was_empty(tmp_path: Path) -> None:
    database = _database(tmp_path)
    calls: list[str] = []
    registry = CapabilityRegistry()

    async def search(_context: object, args: Mapping[str, object]) -> Result:
        calls.append(str(args["query"]))
        return Result(ok=True, data={"results": [{"url": "https://a.test"}]})

    registry.register(
        Capability(
            name="search_web",
            description="cherche",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            risk=Risk.READ,
            run=search,
        )
    )
    tool_calls = (
        ToolCall(id="1", name="search_web", arguments={"query": "a"}),
        ToolCall(id="2", name="search_web", arguments={"query": "b"}),
    )
    client = ScriptedClient(
        [Completion(text="", tool_calls=tool_calls, model="m"), Completion(text="ok", model="m")]
    )
    service = ConversationService(
        database=database,
        client=client,
        capabilities=registry,
        prompt=PromptSections(),
        settings=Settings.for_tests(tmp_path),
        debounce_seconds=0,
    )
    reply = await service.handle(_message(mentioned=True, text="cherche"))
    assert reply is not None
    assert calls == ["a"]
    assert "Une recherche suffit" in str(client.seen[1])
    database.close()


async def test_off_mode_and_bots_get_no_spontaneous_reaction(tmp_path: Path) -> None:
    database = _database(tmp_path)
    engine = _Engine({"ambient_react": True, "join_reaction": True})
    social = Social(database, engine, clock=lambda: _NOW)
    added: list[str] = []

    async def react(_channel: int, _message: int, emoji: str) -> bool:
        added.append(emoji)
        return True

    social.reactor = react
    social.room.bump_attention(5, 7)
    assert await social.consider(_message(text="trop bien !"), enabled=False) == ""
    seen = ReactionSeen(
        guild_id=5,
        channel_id=3,
        message_id=10,
        user_id=8,
        emoji="😂",
        author_id=1,
        author_is_bot=True,
    )
    await social.notice_reaction(seen)
    await social.notice_reaction(replace(seen, user_id=9))
    old = ReactionSeen(
        guild_id=5,
        channel_id=3,
        message_id=11,
        user_id=8,
        emoji="😂",
        author_id=7,
        age_s=7 * 3600,
    )
    await social.notice_reaction(old)
    await social.notice_reaction(replace(old, user_id=9))
    assert added == []
    assert engine.names == []
    database.close()


def test_memory_merge_is_strict_and_proposals_speak_to_the_person() -> None:
    assert not close("j'aime le foot", "j'aime le rugby")
    assert close("Léa habite à Lyon depuis 2020", "Léa habite à Lyon depuis 2020.")
    assert second_person("je suis végétarienne et mon chat dort") == (
        "tu es végétarienne et ton chat dort"
    )
    assert about_someone_else("Paul est végétarien")
    assert not about_someone_else("je suis végétarien")


async def test_memory_lines_name_who_they_are_about(tmp_path: Path) -> None:
    database = _database(tmp_path)
    book = Memories(database, NullIndex(), clock=lambda: _NOW)
    book.store.remember(
        Actor(8, False, False),
        scope="user",
        subject_id=8,
        guild_id=5,
        content="joue du piano",
        source="explicit",
        now=_NOW,
    )
    prompt = book.prompt_for(_message(mentioned_ids=(8,), mentioned_names=((8, "Noé"),)))
    assert "Noé (8) : joue du piano" in prompt
    proposal = book.store.propose(
        scope="guild",
        content="le salon jeux est calme",
        subject_user_id=None,
        guild_id=5,
        channel_id=3,
        source_message_id=1,
        now=_NOW,
    )
    assert [item.id for item in book.store.open_guild(5)] == [proposal.id]
    database.close()


def test_views_split_under_discord_limits_and_links_stay_quiet() -> None:
    cards = tuple(
        card(heading(f"Carte {index}"), text("x" * 900), gallery(["https://img.test/a.png"]))
        for index in range(6)
    )
    views = build_views(intro="Voici https://a.test", cards=cards, outro="-# fin")
    assert len(views) >= 2
    assert quiet_links("voir https://a.test et <https://b.test>") == (
        "voir <https://a.test> et <https://b.test>"
    )
    assert image_url("https://cdn.test/a.gif?ex=1").endswith("&format=png")
    assert image_url("https://cdn.test/a.png") == "https://cdn.test/a.png"


async def test_a_page_behind_a_redirect_is_read() -> None:
    def handler(
        _method: str, url: str, _headers: Mapping[str, str], _body: bytes | None
    ) -> HttpResponse:
        if url == "http://site.test/":
            return HttpResponse(status=301, body=b"", headers={"Location": "https://site.test/"})
        return HttpResponse(status=200, body=b"<p>bonjour</p>", headers={})

    page, final = await fetch_text(FakeHttp(handler), "http://site.test/", resolve=lambda _h: None)
    assert page == "bonjour"
    assert final == "https://site.test/"
