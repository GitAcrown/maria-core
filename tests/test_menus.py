from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import discord

from maria_core.db import Database
from maria_core.discord.memory_menu import MemoryHub, MemoryState
from maria_core.discord.task_menu import TaskHub
from maria_core.llm.types import Completion
from maria_core.memory.policy import Actor
from maria_core.memory.service import Memories
from maria_core.memory.summary import MemorySummaries
from maria_core.objectives.model import Objective
from maria_core.ui.emojis import EVENT_TASK, REPEAT_REMINDER, SMALL_TASK
from maria_core.vectors import NullIndex
from tests.fakes import ScriptedClient

_NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _texts(view: discord.ui.LayoutView) -> str:
    return "\n".join(
        item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)
    )


def _labels(view: discord.ui.LayoutView) -> list[str]:
    return [str(item.label) for item in view.walk_children() if isinstance(item, discord.ui.Button)]


def _fits_discord(view: discord.ui.LayoutView) -> bool:
    return len(list(view.walk_children())) <= 40 and len(_texts(view)) <= 4000


async def test_memory_hub_shows_summary_catalog_and_detail(tmp_path: Path) -> None:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    book = Memories(database, NullIndex(), clock=lambda: _NOW)
    actor = Actor(7, False, False)
    words = [
        "chats",
        "jazz",
        "Lyon",
        "velo",
        "Zelda",
        "sushi",
        "Paris",
        "tennis",
        "Rome",
        "piano",
        "echecs",
        "ski",
        "bd",
        "rap",
        "opera",
        "golf",
        "cafe",
        "yoga",
        "surf",
        "judo",
    ]
    for index, word in enumerate(words):
        book.store.remember(
            actor,
            scope="user",
            subject_id=7,
            guild_id=5,
            content=f"Sujet {word}",
            source="explicit",
            now=_NOW + timedelta(minutes=index),
        )
    book.store.propose(
        scope="user",
        content="Lea habite a Lyon",
        subject_user_id=7,
        guild_id=5,
        channel_id=3,
        source_message_id=None,
        now=_NOW,
    )
    client = ScriptedClient([Completion(text="Tu aimes beaucoup de choses.")])
    app: Any = SimpleNamespace(memory=book, memory_summaries=MemorySummaries(client))
    state = MemoryState(user_id=7, guild_id=5, collective=False, can_manage=False, name="Lea")
    hub = MemoryHub(app, state, actor)
    await hub.load()
    hub.build()
    assert _fits_discord(hub)
    assert "## Mémoire · Lea" in _texts(hub)
    assert "Tu aimes beaucoup de choses." in _texts(hub)
    assert "À valider (1)" in _labels(hub)
    assert {"Ajouter", "→"} <= set(_labels(hub))
    hub.selected, hub.screen = state.memories[0].id, "memory"
    hub.build()
    assert {"Modifier", "Oublier", "← Retour"} <= set(_labels(hub))
    database.close()


def _objective(oid: int, trigger: dict[str, object], **extra: Any) -> Objective:
    fields: dict[str, Any] = {
        "id": oid,
        "owner_id": 7,
        "guild_id": 5,
        "channel_ids": (3,),
        "deliver": "channel",
        "title": f"Tâche {oid}",
        "trigger": trigger,
        "condition": None,
        "action": {"type": "remind", "text": "Sortir le chien"},
        "status": "active",
        "next_run_at": _NOW + timedelta(hours=oid),
        "fires": 0,
        "max_fires": None,
        "cooldown_s": 0,
        "expires_at": None,
        "state": {},
        "version": 1,
        "last_error": "",
    }
    fields.update(extra)
    return Objective(**fields)


async def test_task_hub_names_each_kind_and_confirms_deletion() -> None:
    app: Any = SimpleNamespace()
    hub = TaskHub(app, 7)
    hub.objectives = (
        _objective(1, {"type": "at", "at": "2026-10-14T09:00"}),
        _objective(2, {"type": "daily", "time": "08:00"}),
        _objective(3, {"type": "on_topic", "topic": "jeux"}, action={"type": "alert"}),
        _objective(4, {"type": "daily", "time": "08:00"}, action={"type": "fetch_then"}),
        _objective(5, {"type": "at", "at": "2026-10-15T09:00"}, status="draft"),
        _objective(6, {"type": "at", "at": "2026-10-16T09:00"}),
    )
    hub.build()
    text = _texts(hub)
    assert _fits_discord(hub)
    assert f"### {SMALL_TASK} Tâche 1\n" in text
    assert "-# Rappel · active" in text
    assert "-# Rappel récurrent · active" in text
    assert f"### {REPEAT_REMINDER} Tâche 2" in text
    assert f"### {EVENT_TASK} Tâche 3" in text
    assert "-# Surveillance · en veille" in text
    hub.selected, hub.screen = 2, "detail"
    hub.build()
    assert _labels(hub) == ["Modifier", "Pause", "Passer une fois", "Supprimer", "← Retour"]
    hub.screen, hub.pending = "confirm", "cancel"
    hub.build()
    assert "**Supprimer ?**" in _texts(hub)
    assert "## " in _texts(hub) and "**Quand**" in _texts(hub)  # la fiche reste visible
    assert _labels(hub) == ["Supprimer", "Annuler"]


async def test_task_hub_tabs_filter_by_family_and_only_show_those_present() -> None:
    app: Any = SimpleNamespace()
    hub = TaskHub(app, 7)
    hub.objectives = (
        _objective(1, {"type": "at", "at": "2026-10-14T09:00"}),
        _objective(2, {"type": "on_topic", "topic": "jeux"}, action={"type": "alert"}),
        _objective(3, {"type": "at", "at": "2026-10-16T09:00"}),
    )
    hub.build()
    tabs = [item for item in hub.children[0].children if isinstance(item, discord.ui.Button)]
    assert [tab.label for tab in tabs] == ["Tout (3)", "Rappels (2)", "Écoutes (1)"]
    assert tabs[0].style == discord.ButtonStyle.primary
    hub.group = "listening"
    hub.build()
    assert "Tâche 2" in _texts(hub) and "Tâche 1" not in _texts(hub)


async def test_no_button_of_the_menus_carries_an_icon() -> None:
    app: Any = SimpleNamespace()
    hub = TaskHub(app, 7)
    hub.objectives = (
        _objective(1, {"type": "at", "at": "2026-10-14T09:00"}),
        _objective(2, {"type": "on_topic", "topic": "jeux"}, action={"type": "alert"}),
    )
    for screen in ("catalog", "detail", "confirm"):
        hub.selected, hub.screen, hub.pending = 1, screen, "cancel"
        hub.build()
        buttons = [i for i in hub.walk_children() if isinstance(i, discord.ui.Button)]
        assert buttons and all(button.emoji is None for button in buttons), screen
    hub.screen = "detail"
    hub.build()
    assert "← Retour" in _labels(hub)
