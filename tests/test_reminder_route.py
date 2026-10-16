"""Un rappel dit où il part (salon ou message privé) et ne s'adresse jamais qu'à son auteur."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maria_core.capabilities import CapabilityRegistry, Context
from maria_core.capabilities.builtin.layout import render_created, render_draft
from maria_core.capabilities.runner import invoke
from maria_core.config import Settings
from maria_core.db import Database
from maria_core.discord.task_menu import objective_facts
from maria_core.llm.schema import openai_tool
from maria_core.llm.types import ToolCall
from maria_core.objectives import Objectives
from maria_core.objectives.labels import route
from maria_core.objectives.schemas import GUIDE
from maria_core.objectives.tools import objective_capabilities

_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _service(tmp_path: Path) -> tuple[Objectives, Database]:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    return Objectives(database, clock=lambda: _NOW), database


def _context(guild: int | None = 5) -> Context:
    return Context(
        user_id=7,
        guild_id=guild,
        channel_id=3,
        message_id=99,
        is_owner=False,
        is_moderator=False,
        text="rappelle",
    )


async def _create(service: Objectives, tmp_path: Path, guild: int | None = 5, **fields: Any):
    registry = CapabilityRegistry()
    for capability in objective_capabilities(service):
        registry.register(capability)
    base = {"title": "Dossier", "trigger_type": "at", "in_minutes": 60, "action_type": "remind"}
    call = ToolCall(
        id="1", name="objective_create", arguments={**base, "text": "Dossier", **fields}
    )
    return await invoke(registry, Settings.for_tests(tmp_path), _context(guild), call)


async def test_a_reminder_says_where_it_will_be_sent(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    channel = await _create(service, tmp_path)
    assert channel.ok and channel.widget == "objective_created"
    assert channel.data["where"] == "dans <#3>" and "for" not in channel.data
    text = render_created(channel.data).cards[0].as_text()
    assert "**Envoi** · dans <#3>" in text and "Pour" not in text
    private = await _create(service, tmp_path, deliver="dm", in_minutes=90)
    assert private.data["where"] == "en message privé"
    saved = service.store.get(int(channel.data["id"]))
    assert saved is not None and route(saved) == "dans <#3>"
    assert "**Envoi** · dans <#3>" in objective_facts(saved)
    database.close()


async def test_a_draft_also_says_where_it_will_be_sent(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    draft = await _create(service, tmp_path, trigger_type="daily", time="09:00", in_minutes=None)
    assert draft.widget == "objective_draft" and draft.data["status"] == "draft"
    assert "**Envoi** · dans <#3>" in render_draft(draft.data).cards[0].as_text()
    database.close()


async def test_a_reminder_is_only_ever_for_the_person_who_asks(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    schema = openai_tool(objective_capabilities(service)[0])["function"]["parameters"]
    assert "for_user_id" not in schema["properties"]
    assert "ne peux pas programmer un rappel" in GUIDE
    refused = await _create(service, tmp_path, for_user_id="8")  # l'argument n'existe plus
    assert not refused.ok
    own = await _create(service, tmp_path)
    saved = service.store.get(int(own.data["id"]))
    assert saved is not None and saved.owner_id == 7
    database.close()
