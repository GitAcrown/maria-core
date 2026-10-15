"""/moi : profil, souvenirs, appris récemment, à valider, sous une seule rangée d'onglets."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import discord

from maria_core.db import Database
from maria_core.discord.me_menu import MeHub
from maria_core.discord.memory_menu import MemoryHub, MemoryState
from maria_core.discord.profile_menu import ProfileHub
from maria_core.llm.types import Completion
from maria_core.memory.policy import Actor
from maria_core.memory.service import Memories
from maria_core.memory.summary import MemorySummaries
from maria_core.profile import Profiles
from maria_core.vectors import NullIndex
from tests.fakes import ScriptedClient

_NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _texts(view: discord.ui.LayoutView) -> str:
    return "\n".join(
        item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)
    )


def _tabs(view: discord.ui.LayoutView) -> list[discord.ui.Button]:
    first = view.children[0]
    assert isinstance(first, discord.ui.ActionRow)
    return [item for item in first.children if isinstance(item, discord.ui.Button)]


async def _hub(tmp_path: Path) -> tuple[MeHub, Database]:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    book = Memories(database, NullIndex(), clock=lambda: _NOW)
    actor = Actor(7, False, False)
    book.store.remember(
        actor,
        scope="user",
        subject_id=7,
        guild_id=5,
        content="Aime le jazz",
        source="explicit",
        now=_NOW,
    )
    book.store.propose(
        scope="user",
        content="Léa habite à Lyon",
        subject_user_id=7,
        guild_id=5,
        channel_id=3,
        source_message_id=None,
        now=_NOW,
    )
    profiles = Profiles(database, clock=lambda: _NOW)
    profiles.store.set(7, "city", "Lyon", _NOW)
    client = ScriptedClient([Completion(text="Tu aimes le jazz.")])
    app: Any = SimpleNamespace(
        memory=book, memory_summaries=MemorySummaries(client), profiles=profiles
    )
    state = MemoryState(user_id=7, guild_id=5, collective=False, can_manage=False, name="Léa")
    hub = MeHub(MemoryHub(app, state, actor), ProfileHub(app, 7, "Léa"))
    await hub.load()
    return hub, database


async def test_the_merged_menu_opens_on_the_profile_with_one_tab_row(tmp_path: Path) -> None:
    hub, database = await _hub(tmp_path)
    hub.build()
    tabs = _tabs(hub)
    assert [tab.label for tab in tabs] == ["Profil", "Souvenirs", "À valider (1)"]
    assert tabs[0].style == discord.ButtonStyle.primary
    assert "**Ville** · Lyon" in _texts(hub)
    assert len(list(hub.walk_children())) <= 40
    database.close()


async def test_each_tab_shows_its_panel_and_keeps_the_tab_row(tmp_path: Path) -> None:
    hub, database = await _hub(tmp_path)
    hub.tab = "memories"
    hub.build()
    assert "Aime le jazz" in _texts(hub) and "Tu aimes le jazz." in _texts(hub)
    assert _tabs(hub)[1].style == discord.ButtonStyle.primary
    hub.tab = "proposals"
    hub.build()
    assert _tabs(hub)[2].style == discord.ButtonStyle.primary
    database.close()


async def test_a_panel_screen_keeps_the_tabs_and_refreshes_through_the_host(tmp_path: Path) -> None:
    hub, database = await _hub(tmp_path)
    hub.tab = "memories"
    memory = hub.memory.state.memories[0]
    hub.memory.selected, hub.memory.screen = memory.id, "memory"
    hub.build()
    assert [tab.label for tab in _tabs(hub)][:2] == ["Profil", "Souvenirs"]
    assert "Modifier" in [b.label for b in hub.walk_children() if isinstance(b, discord.ui.Button)]
    hub.tab = "profile"
    hub.profile.selected, hub.profile.screen = "city", "slot"
    hub.build()
    assert _tabs(hub)[0].style == discord.ButtonStyle.primary
    assert hub.memory.host is hub and hub.profile.host is hub
    database.close()
