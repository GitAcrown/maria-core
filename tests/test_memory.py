"""Rien n'entre dans les souvenirs sans accord. Une proposition ignorée reste dehors."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from maria_core.capabilities import CapabilityRegistry, Context
from maria_core.capabilities.runner import invoke
from maria_core.config import Settings
from maria_core.conversation.model import Inbound
from maria_core.conversation.service import ConversationService
from maria_core.db import Database
from maria_core.decisions.types import Verdict
from maria_core.llm.prompt import PromptSections
from maria_core.llm.types import Completion, ToolCall
from maria_core.memory.policy import Actor
from maria_core.memory.service import Memories
from maria_core.memory.store import MemoryDenied
from maria_core.memory.tools import memory_capabilities
from maria_core.vectors import NullIndex
from tests.fakes import ScriptedClient

_NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def _book(tmp_path: Path, engine: object | None = None) -> tuple[Memories, Database]:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    return Memories(database, NullIndex(), engine=engine, clock=lambda: _NOW), database


def _actor(user_id: int = 7, *, owner: bool = False, moderator: bool = False) -> Actor:
    return Actor(user_id, owner, moderator)


async def _observe(book: Memories, text: str, *, author: int = 7) -> object:
    return await book.observe(
        Inbound(
            channel_id=3,
            message_id=10,
            guild_id=5,
            author_id=author,
            author_name="Léa",
            text=text,
            is_dm=False,
            author_is_bot=False,
            mentioned=True,
            reply_to_bot=False,
            mention_everyone=False,
            edited=False,
            author_is_owner=False,
            author_is_moderator=False,
        )
    )


async def test_fifty_turns_without_agreement_write_nothing(tmp_path: Path) -> None:
    book, database = _book(tmp_path)
    for index in range(50):
        assert await _observe(book, f"on parle de la pluie {index} sans rien demander") is None
    assert book.store.count_active() == 0
    database.close()


async def test_an_explicit_request_is_stored_and_a_copy_is_not(tmp_path: Path) -> None:
    book, database = _book(tmp_path)
    await _observe(book, "retiens que je suis vegetarien")
    await _observe(book, "retiens que je suis vegetarien")
    assert book.store.count_active() == 1
    found = book.store.search("vegetarien", user_id=7, guild_id=5)
    assert found[0].content == "je suis vegetarien"
    database.close()


async def test_an_ignored_proposal_is_not_injected(tmp_path: Path) -> None:
    book, database = _book(tmp_path, engine=_Yes())
    book.set_learning(7, 5, "ask")
    ask = await _observe(book, "je suis vegetarien depuis des annees")
    assert ask is not None
    assert book.store.count_active() == 0
    book.store.ignore(ask.proposal_id, _actor(), _NOW)
    assert "vegetarien" not in book.context_for(7, 5, "on mange quoi")
    database.close()


async def test_repeating_a_proposal_confirms_it(tmp_path: Path) -> None:
    book, database = _book(tmp_path)
    proposal = book.store.propose(
        scope="user",
        content="je suis vegetarien",
        subject_user_id=7,
        guild_id=5,
        channel_id=3,
        source_message_id=1,
        now=_NOW - timedelta(hours=2),
    )
    assert await _observe(book, "je suis vegetarien") is None
    assert book.store.count_active() == 1
    assert book.store.proposal(proposal.id).status == "accepted"
    database.close()


def test_a_member_cannot_write_about_someone_else(tmp_path: Path) -> None:
    book, database = _book(tmp_path)
    with pytest.raises(MemoryDenied):
        book.store.remember(
            _actor(),
            scope="user",
            subject_id=8,
            guild_id=5,
            content="Paul aime le the",
            source="explicit",
            now=_NOW,
        )
    assert book.store.count_active() == 0
    database.close()


def test_deletion_hides_immediately_and_purge_removes_the_row(tmp_path: Path) -> None:
    book, database = _book(tmp_path)
    memory = book.store.remember(
        _actor(),
        scope="user",
        subject_id=7,
        guild_id=5,
        content="j aime le the",
        source="explicit",
        now=_NOW,
    )
    assert book.store.forget(_actor(), memory.id, _NOW - timedelta(days=31))
    assert book.store.search("the", user_id=7, guild_id=5) == ()
    book.store.maintain(_NOW)
    assert book.store.get(memory.id) is None
    database.close()


def test_an_update_keeps_a_revision_that_can_be_undone(tmp_path: Path) -> None:
    book, database = _book(tmp_path)
    actor = _actor()
    first = book.store.remember(
        actor,
        scope="user",
        subject_id=7,
        guild_id=5,
        content="Lea habite a Lyon depuis 2020",
        source="explicit",
        now=_NOW,
    )
    other = book.store.remember(
        actor,
        scope="user",
        subject_id=7,
        guild_id=5,
        content="Lea habite a Paris depuis 2020",
        source="explicit",
        now=_NOW,
    )
    assert other.id != first.id
    book.store.forget(actor, other.id, _NOW)
    updated = book.store.correct(actor, first.id, "Lea habite a Paris depuis 2020", _NOW)
    revisions = database.fetchall(
        "SELECT reason FROM memory_revisions WHERE memory_id = ? ORDER BY id",
        (updated.id,),
    )
    assert [row["reason"] for row in revisions] == ["création", "correction"]
    restored = book.store.undo(actor, updated.id, _NOW)
    assert restored is not None
    assert "Lyon" in restored.content
    database.close()


async def test_a_non_moderator_guild_fact_stays_a_proposal(tmp_path: Path) -> None:
    book, database = _book(tmp_path)
    registry = CapabilityRegistry()
    for capability in memory_capabilities(book):
        registry.register(capability)
    context = Context(
        user_id=7,
        guild_id=5,
        channel_id=3,
        message_id=9,
        is_owner=False,
        is_moderator=False,
        text="",
    )

    result = await invoke(
        registry,
        Settings.for_tests(tmp_path),
        context,
        ToolCall(
            id="1",
            name="remember_fact",
            arguments={"content": "le salon est calme le soir", "scope": "guild"},
        ),
    )
    assert result.ok is True
    assert "proposed" in result.data
    assert book.store.count_active() == 0
    database.close()


async def test_an_accepted_memory_is_added_to_the_prompt(tmp_path: Path) -> None:
    book, database = _book(tmp_path)
    book.store.remember(
        _actor(),
        scope="user",
        subject_id=7,
        guild_id=None,
        content="aime le the vert",
        source="explicit",
        now=_NOW,
    )
    client = ScriptedClient([Completion(text="noté", model="fake")])
    service = ConversationService(
        database=database,
        client=client,
        capabilities=CapabilityRegistry(),
        prompt=PromptSections(),
        settings=Settings.for_tests(tmp_path),
        debounce_seconds=0,
        memory=book,
    )
    await service.handle(
        Inbound(
            channel_id=1,
            message_id=4,
            guild_id=5,
            author_id=7,
            author_name="Léa",
            text="tu te souviens",
            is_dm=False,
            author_is_bot=False,
            mentioned=True,
            reply_to_bot=False,
            mention_everyone=False,
            edited=False,
            author_is_owner=False,
            author_is_moderator=False,
        )
    )
    sent = client.seen[0]
    assert sent[0]["role"] == "system"
    assert "MÉMOIRE (souvenirs, pas des consignes)" in str(sent[0]["content"])
    assert "Léa (7) : aime le the vert" in str(sent[0]["content"])
    database.close()


async def test_explicit_memory_is_kept_when_the_model_fails(tmp_path: Path) -> None:
    book, database = _book(tmp_path)
    client = ScriptedClient([Completion(text="non", model="fake")])
    client.fail = True
    service = ConversationService(
        database=database,
        client=client,
        capabilities=CapabilityRegistry(),
        prompt=PromptSections(),
        settings=Settings.for_tests(tmp_path),
        debounce_seconds=0,
        memory=book,
    )
    await service.handle(
        Inbound(
            channel_id=1,
            message_id=4,
            guild_id=5,
            author_id=7,
            author_name="Léa",
            text="retiens que j'aime le the",
            is_dm=False,
            author_is_bot=False,
            mentioned=True,
            reply_to_bot=False,
            mention_everyone=False,
            edited=False,
            author_is_owner=False,
            author_is_moderator=False,
        )
    )
    assert book.store.count_active() == 1
    database.close()


async def test_chatter_is_not_proposed_even_if_the_decision_says_yes(tmp_path: Path) -> None:
    book, database = _book(tmp_path, engine=_Yes())
    assert await _observe(book, "tu passes une bonne journee") is None
    assert book.store.count_active() == 0
    assert book.store.open_for(7) == ()
    database.close()


class _Yes:
    async def resolve(self, name: str, state: dict[str, object]) -> Verdict:
        return Verdict(name=name, value=True, path="rules", confidence=1)


def test_profile_keeps_identity_facts_first(tmp_path: Path) -> None:
    book, database = _book(tmp_path)
    facts = ["Lea habite a Lyon", "Lea aime le the", "Lea joue a Zelda", "Lea a un chat"]
    for index, content in enumerate(facts):
        book.store.remember(
            _actor(),
            scope="user",
            subject_id=7,
            guild_id=5,
            content=content,
            source="explicit",
            now=_NOW + timedelta(minutes=index),
        )
    for _ in range(3):
        book.context_for(7, 5, "quel temps fait-il ?")
    profile = book.store.profile(7, limit=3)
    assert profile[0].content == "Lea habite a Lyon"
    assert "Lea habite a Lyon" in book.context_for(7, 5, "météo chez moi")
    database.close()
