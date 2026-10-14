"""Ce que MARIA_R faisait en coulisses : cache des outils, galerie fusionnée, erreurs, heures."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import discord
import pytest

from maria_core.capabilities import Capability, CapabilityRegistry, Context, Result, Risk
from maria_core.capabilities.builtin.web import render_images
from maria_core.capabilities.cache import ResultCache
from maria_core.capabilities.runner import CACHE, invoke
from maria_core.config import Settings
from maria_core.conversation.compose import compose
from maria_core.db import Database
from maria_core.discord.bot import on_app_command_error
from maria_core.discord.commands.usage import usage_report
from maria_core.discord.task_edit import when_changes
from maria_core.llm.loop import LoopResult, ToolRecord
from maria_core.llm.types import ToolCall
from maria_core.ui.widgets import WidgetRegistry


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


async def test_public_results_are_cached_per_arguments(tmp_path) -> None:
    calls: list[str] = []

    async def run(_context: Context, args: Any) -> Result:
        calls.append(str(args["city"]))
        return Result(ok=True, data={"city": args["city"]})

    registry = CapabilityRegistry()
    registry.register(
        Capability(
            name="cached_probe",
            description="Sonde",
            parameters={"type": "object", "properties": {"city": {"type": "string"}}},
            risk=Risk.READ,
            run=run,
            cache_s=60,
        )
    )
    CACHE.clear()
    settings = Settings.for_tests(tmp_path)
    for city in ("Lyon", " lyon ", "Paris", "Lyon"):
        result = await invoke(
            registry,
            settings,
            _context(),
            ToolCall(id="1", name="cached_probe", arguments={"city": city}),
        )
        assert result.ok
    assert calls == ["Lyon", "Paris"]


def test_failures_and_expired_entries_are_not_served() -> None:
    now = [0.0]
    cache = ResultCache(clock=lambda: now[0])
    cache.put("x", {"a": 1}, Result(ok=False, data={}, error="non"), 10)
    assert cache.get("x", {"a": 1}) is None
    cache.put("x", {"a": 1}, Result(ok=True, data={"v": 1}), 10)
    assert cache.get("x", {"a": 1}) is not None
    now[0] = 11.0
    assert cache.get("x", {"a": 1}) is None


def test_several_image_searches_become_one_gallery() -> None:
    widgets = WidgetRegistry()
    widgets.register("search_images", render_images)

    def record(query: str, url: str) -> ToolRecord:
        data = {"query": query, "images": [{"url": url, "title": query}]}
        result = Result(ok=True, data=data, widget="search_images")
        return ToolRecord("search_images", {"query": query}, result)

    records = (record("chat", "https://a.fr/1.png"), record("chien", "https://a.fr/2.png"))
    outcome = LoopResult("Voilà", ("search_images",) * 2, 2, 0, 0, "m", 0, True, records=records)
    composed = compose(outcome, widgets, ("maria",))
    assert len(composed.cards) == 1
    assert composed.cards[0].blocks[0].urls == ("https://a.fr/1.png", "https://a.fr/2.png")


def test_when_is_parsed_for_the_kind_of_program() -> None:
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    assert when_changes("daily", "8h05", now) == {"time": "08:05"}
    assert when_changes("at", "25/12 18:30", now) == {"at": "2026-12-25T18:30"}
    assert when_changes("at", "01/01 09:00", now) == {"at": "2027-01-01T09:00"}
    assert when_changes("daily", "", now) == {}
    with pytest.raises(ValueError):
        when_changes("daily", "bientôt", now)
    with pytest.raises(ValueError):
        when_changes("on_topic", "18:00", now)


async def test_a_failing_slash_command_still_answers() -> None:
    sent: list[str] = []

    async def send_message(text: str, **_kw: Any) -> None:
        sent.append(text)

    interaction: Any = SimpleNamespace(
        response=SimpleNamespace(is_done=lambda: False, send_message=send_message),
        followup=SimpleNamespace(),
    )
    await on_app_command_error(interaction, discord.app_commands.AppCommandError("boom"))
    await on_app_command_error(
        interaction, discord.app_commands.MissingPermissions(["manage_messages"])
    )
    assert sent[0].startswith("**Erreur ·**")
    assert "manage_messages" in sent[1]


async def test_usage_report_summarises_model_and_tool_calls(tmp_path) -> None:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    stamp = now.isoformat()
    database.execute(
        "INSERT INTO llm_calls (at, purpose, model, input_tokens, output_tokens, duration_ms, ok)"
        " VALUES (?, 'conversation', 'm', 2500, 300, 900, 1)",
        (stamp,),
    )
    for ok in (1, 0):
        database.execute(
            "INSERT INTO capability_calls (at, name, guild_id, user_id, ok, duration_ms, error)"
            " VALUES (?, 'get_weather', 5, 7, ?, 400, '')",
            (stamp, ok),
        )
    text, meta = usage_report(database, now)
    assert "**conversation** · m · 1 appel(s) · 2.5k → 300" in text
    assert "`get_weather` · 2 appel(s) · 400 ms · **1 échec(s)**" in text
    assert meta == "7 derniers jours"
    database.close()
