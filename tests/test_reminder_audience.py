"""Un rappel dit pour qui il est (toi ou un autre membre) et où il part (salon ou message privé)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maria_core.capabilities import CapabilityRegistry, Context
from maria_core.capabilities.builtin.layout import render_created, render_draft
from maria_core.capabilities.runner import invoke
from maria_core.config import Settings
from maria_core.db import Database
from maria_core.discord.task_menu import objective_facts
from maria_core.llm.types import ToolCall
from maria_core.objectives import Objectives
from maria_core.objectives.labels import recipient, route
from maria_core.objectives.tools import objective_capabilities

_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _service(tmp_path: Path, members: dict[int, str] | None = None) -> tuple[Objectives, Database]:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    service = Objectives(database, clock=lambda: _NOW)
    known = {8: "Paul", **(members or {})}

    async def member_name(_guild: int, user_id: int) -> str | None:
        return known.get(user_id)

    service.member_name = member_name
    return service, database


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


async def test_a_reminder_for_yourself_says_who_and_where(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    channel = await _create(service, tmp_path)
    assert channel.ok and channel.widget == "objective_created"
    assert channel.data["for"] == "toi" and channel.data["where"] == "dans <#3>"
    text = render_created(channel.data).cards[0].as_text()
    assert "**Pour** · toi" in text and "**Envoi** · dans <#3>" in text
    private = await _create(service, tmp_path, deliver="dm", in_minutes=90)
    assert private.data["where"] == "en message privé" and private.data["for"] == "toi"
    database.close()


async def test_a_reminder_for_someone_else_is_a_draft_that_names_them(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    result = await _create(service, tmp_path, for_user_id="8", deliver="dm")
    assert result.ok and result.widget == "objective_draft"
    assert result.data["status"] == "draft"
    assert result.data["for"] == "Paul" and result.data["where"] == "en message privé à Paul"
    card = render_draft(result.data).cards[0].as_text()
    assert "**Pour** · Paul" in card and "**Envoi** · en message privé à Paul" in card
    saved = service.store.get(int(result.data["id"]))
    assert saved is not None and saved.target_id == 8 and saved.owner_id == 7
    assert recipient(saved, mention=True) == "<@8>" and recipient(saved) == "Paul"
    assert route(saved, mention=True) == "en message privé à <@8>"
    assert "**Pour** · <@8>" in objective_facts(saved)
    in_channel = await _create(service, tmp_path, for_user_id="8", in_minutes=120)
    assert in_channel.data["where"] == "dans <#3>"
    database.close()


async def test_a_reminder_for_someone_else_has_firm_limits(tmp_path: Path) -> None:
    service, database = _service(tmp_path)
    unknown = await _create(service, tmp_path, for_user_id="999")
    assert not unknown.ok and "ne trouve pas" in unknown.error
    private = await _create(service, tmp_path, guild=None, for_user_id="8")
    assert not private.ok and "serveur" in private.error
    for bad in (
        {"trigger_type": "daily", "time": "09:00", "in_minutes": None},
        {"trigger_type": "on_topic", "pattern": "jeu", "in_minutes": None},
        {"action_type": "alert", "text": "x"},
    ):
        refused = await _create(service, tmp_path, for_user_id="8", **bad)
        assert not refused.ok and "à date ou à heure" in refused.error, bad
    for minutes in (30, 45, 60):
        assert (await _create(service, tmp_path, for_user_id="8", in_minutes=minutes)).ok
    fourth = await _create(service, tmp_path, for_user_id="8", in_minutes=75)
    assert not fourth.ok and "3 rappels en attente pour d'autres" in fourth.error
    assert (
        await _create(service, tmp_path, in_minutes=75)
    ).ok  # pour soi : aucune limite de ce genre
    database.close()
