"""Branche les capacités du noyau. Les médias restent des extensions."""

from datetime import datetime
from typing import Protocol

from maria_core.capabilities import CapabilityRegistry
from maria_core.capabilities.builtin.about import about_capability
from maria_core.capabilities.builtin.layout import (
    layout_capabilities,
    render_draft,
    render_table,
    render_widget,
)
from maria_core.capabilities.builtin.python_tool import python_capability
from maria_core.capabilities.builtin.summary import Condense, summary_capability
from maria_core.capabilities.builtin.web import render_images, web_capabilities
from maria_core.capabilities.http import HttpClient
from maria_core.capabilities.ports import ChannelReader
from maria_core.config import Settings
from maria_core.db import Database
from maria_core.llm.prompt import PromptSections
from maria_core.memory.service import Memories
from maria_core.memory.tools import memory_capabilities
from maria_core.objectives.runtime import Objectives
from maria_core.objectives.schemas import GUIDE
from maria_core.objectives.tools import objective_capabilities
from maria_core.ui import WidgetRegistry


class _Transcript(Protocol):
    def transcript(self, channel_id: int) -> tuple[str, ...]: ...


class _Seen(Protocol):
    def away_since(self, user_id: int, channel_id: int) -> datetime | None: ...


class _Social(Protocol):
    seen: _Seen


class BuiltinHost(Protocol):
    settings: Settings
    database: Database
    http: HttpClient
    capabilities: CapabilityRegistry
    widgets: WidgetRegistry
    prompt: PromptSections
    conversation: _Transcript
    channel_reader: ChannelReader | None
    objectives: Objectives
    memory: Memories
    social: _Social


def register_builtins(app: BuiltinHost, condense: Condense | None = None) -> None:
    for capability in web_capabilities(app.http, app.settings.brave_api_key):
        app.capabilities.register(capability)
    app.capabilities.register(about_capability(app.capabilities))
    app.capabilities.register(
        summary_capability(
            app.conversation.transcript,
            lambda: app.channel_reader,
            condense,
            app.social.seen.away_since,
        )
    )
    app.capabilities.register(python_capability(app.database))
    for capability in (*objective_capabilities(app.objectives), *memory_capabilities(app.memory)):
        app.capabilities.register(capability)
    for capability in layout_capabilities():
        app.capabilities.register(capability)
    app.widgets.register("search_images", render_images)
    app.widgets.register("render_widget", render_widget)
    app.widgets.register("render_table", render_table)
    app.widgets.register("objective_draft", render_draft)
    app.prompt.register_section("objectives", lambda: GUIDE, order=5)
