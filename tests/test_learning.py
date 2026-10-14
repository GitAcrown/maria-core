"""Mémoire silencieuse : MARIA retient seule, remplace ce qui n'est plus vrai, laisse annuler."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import discord
import pytest

from maria_core.conversation.model import Inbound
from maria_core.db import Database
from maria_core.decisions.rules import sensitivity_rules
from maria_core.decisions.types import Verdict
from maria_core.discord.memory_menu import MemoryHub, MemoryState
from maria_core.llm.types import Completion
from maria_core.memory.policy import Actor
from maria_core.memory.service import Memories
from maria_core.memory.summary import MemorySummaries
from maria_core.memory.text import collective_fact
from maria_core.vectors import NullIndex
from tests.fakes import ScriptedClient

_NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


class _Engine:
    """Tout est digne d'être retenu ; `memory_conflict` répond ce qu'on lui a dit."""

    def __init__(self, conflict: str = "keep") -> None:
        self.conflict = conflict
        self.asked: list[tuple[str, dict[str, object]]] = []

    async def resolve(self, name: str, state: dict[str, object]) -> Verdict:
        self.asked.append((name, state))
        value: object = self.conflict if name == "memory_conflict" else True
        return Verdict(name=name, value=value, path="rules", confidence=1)


def _book(tmp_path: Path, engine: object) -> tuple[Memories, Database]:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    return Memories(database, NullIndex(), engine=engine, clock=lambda: _NOW), database


def _message(text: str, *, author: int = 7, guild: int | None = 5) -> Inbound:
    return Inbound(
        channel_id=3,
        message_id=10,
        guild_id=guild,
        author_id=author,
        author_name="Lea",
        text=text,
        is_dm=guild is None,
        author_is_bot=False,
        mentioned=True,
        reply_to_bot=False,
        mention_everyone=False,
        edited=False,
        author_is_owner=False,
        author_is_moderator=False,
    )


async def test_a_clear_fact_is_kept_without_asking_and_shown_afterwards(tmp_path: Path) -> None:
    book, database = _book(tmp_path, _Engine())
    ask = await book.observe(_message("je suis vegetarien depuis des annees"))
    assert ask is not None and ask.learned_id is not None and ask.proposal_id is None
    assert ask.text == "-# 🧠 Retenu : tu es vegetarien depuis des annees"
    assert book.store.count_active() == 1
    assert [item.id for item in book.learned.recent(7, _NOW)] == [ask.learned_id]
    assert book.store.open_for(7) == ()
    again = await book.observe(_message("je suis vegetarien depuis des annees"))
    assert again is None  # déjà connu : aucune trace
    database.close()


async def test_a_new_fact_that_contradicts_an_old_one_replaces_it_and_can_be_undone(
    tmp_path: Path,
) -> None:
    engine = _Engine(conflict="replace")
    book, database = _book(tmp_path, engine)
    actor = Actor(7, False, False)
    book.store.remember(
        actor,
        scope="user",
        subject_id=7,
        guild_id=5,
        content="j'habite à Lyon depuis des années",
        source="explicit",
        now=_NOW - timedelta(days=30),
    )
    ask = await book.observe(_message("j'habite à Paris maintenant depuis un mois"))
    assert ask is not None and ask.learned_id is not None
    assert "au lieu de « tu habites à Lyon depuis des années »" in ask.text
    assert book.store.count_active() == 1
    memory = book.store.get(ask.learned_id)
    assert memory is not None and "Paris" in memory.content
    book.store.undo(actor, ask.learned_id, _NOW)
    book.learned.clear(ask.learned_id)
    restored = book.store.get(ask.learned_id)
    assert restored is not None and "Lyon" in restored.content
    assert book.learned.recent(7, _NOW) == ()
    assert any(name == "memory_conflict" for name, _ in engine.asked)
    database.close()


async def test_compatible_facts_are_both_kept(tmp_path: Path) -> None:
    book, database = _book(tmp_path, _Engine(conflict="keep"))
    await book.observe(_message("j'aime les chats depuis toujours"))
    await book.observe(_message("j'aime aussi la pizza napolitaine"))
    assert book.store.count_active() == 2
    database.close()


async def test_the_three_modes_ask_nothing_or_forget(tmp_path: Path) -> None:
    book, database = _book(tmp_path, _Engine())
    assert book.learning_mode(7, 5) == "auto"
    book.set_learning(7, 5, "ask")
    ask = await book.observe(_message("je suis vegetarien depuis des annees"))
    assert ask is not None and ask.proposal_id is not None and book.store.count_active() == 0
    book.set_learning(7, 5, "off")
    assert await book.observe(_message("je suis gaucher depuis toujours")) is None
    assert book.store.count_active() == 0
    with pytest.raises(ValueError):
        book.set_learning(7, 5, "peut-etre")
    assert book.learning_mode(7, None) == "off"
    database.close()


async def test_a_group_habit_goes_to_the_moderators_never_straight_to_memory(
    tmp_path: Path,
) -> None:
    book, database = _book(tmp_path, _Engine())
    text = "ici c'est une tradition de jouer au Skribbl le vendredi soir"
    assert collective_fact(text)
    assert await book.observe(_message(text)) is None
    assert book.store.list_guild(5) == ()
    waiting = book.store.open_guild(5)
    assert len(waiting) == 1 and waiting[0].subject_user_id is None
    await book.observe(_message(text, author=8))
    assert len(book.store.open_guild(5)) == 1  # pas de doublon
    assert collective_fact("c'est quoi la tradition ?") == ""
    database.close()


async def test_the_recently_learned_tab_lists_what_maria_kept_and_lets_you_undo(
    tmp_path: Path,
) -> None:
    book, database = _book(tmp_path, _Engine())
    ask = await book.observe(_message("je suis vegetarien depuis des annees"))
    assert ask is not None and ask.learned_id is not None
    client = ScriptedClient([Completion(text="Tu es vegetarien.")])
    app: Any = SimpleNamespace(memory=book, memory_summaries=MemorySummaries(client))
    state = MemoryState(user_id=7, guild_id=5, collective=False, can_manage=False, name="Lea")
    hub = MemoryHub(app, state, Actor(7, False, False))
    await hub.load()
    hub.build()
    labels = [str(i.label) for i in hub.walk_children() if isinstance(i, discord.ui.Button)]
    assert "Appris récemment (1)" in labels
    hub.tab = "recent"
    hub.build()
    texts = "\n".join(
        item.content for item in hub.walk_children() if isinstance(item, discord.ui.TextDisplay)
    )
    assert "vegetarien depuis des annees" in texts and "à l'instant" in texts
    hub.selected, hub.screen = ask.learned_id, "memory"
    hub.build()
    labels = [str(i.label) for i in hub.walk_children() if isinstance(i, discord.ui.Button)]
    assert {"Modifier", "Oublier", "Annuler la modif"} <= set(labels)
    database.close()


async def test_a_sensitive_fact_is_asked_about_never_kept_silently(tmp_path: Path) -> None:
    class Sensitive(_Engine):
        async def resolve(self, name: str, state: dict[str, object]) -> Verdict:
            if name == "fact_sensitivity":
                return Verdict(name=name, value="sensitive", path="rules", confidence=1)
            return await super().resolve(name, state)

    book, database = _book(tmp_path, Sensitive())
    ask = await book.observe(_message("je suis suivi par un psy depuis des mois"))
    assert ask is not None and ask.proposal_id is not None and ask.learned_id is None
    assert ask.text.endswith("?")
    assert book.store.count_active() == 0
    database.close()


def test_obvious_sensitive_words_are_caught_without_a_model() -> None:
    assert sensitivity_rules({"text": "je fais une dépression"}).value == "sensitive"
    assert sensitivity_rules({"text": "je suis musulman et je vote à gauche"}).value == "sensitive"
    assert sensitivity_rules({"text": "j'habite à Lyon et j'adore les chats"}) is None
