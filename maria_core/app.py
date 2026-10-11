"""Assemble la configuration, la base et les extensions. Ne connaît pas Discord."""

from __future__ import annotations

import logging

from maria_core.capabilities import CapabilityRegistry
from maria_core.capabilities.builtin.discord_info import discord_capabilities
from maria_core.capabilities.builtin.polls import poll_capability
from maria_core.capabilities.http import UrllibHttpClient
from maria_core.capabilities.ports import ChannelReader, GuildDirectory, PollPoster
from maria_core.capabilities.register import register_builtins
from maria_core.commands import CommandCatalog
from maria_core.config import Settings
from maria_core.conversation import ConversationService
from maria_core.conversation.persona import clock_section, default_personality
from maria_core.db import Database
from maria_core.decisions import DecisionRegistry
from maria_core.decisions.catalog import builtin_decisions
from maria_core.decisions.engine import DecisionEngine
from maria_core.decisions.structured import JevBackend
from maria_core.events import EventBus
from maria_core.llm.client import OpenAIChatClient
from maria_core.llm.prompt import PromptSections
from maria_core.memory import Memories
from maria_core.objectives import Objectives, ObjectiveSignal
from maria_core.objectives.fetch import http_fetcher
from maria_core.plugins import PluginManager
from maria_core.social.service import Social
from maria_core.ui import WidgetRegistry
from maria_core.ui.tabs import TabStore
from maria_core.vectors import NullIndex
from maria_core.vectors.chroma import open_index
from maria_core.vectors.index import VectorIndex

logger = logging.getLogger(__name__)


class App:
    """Hôte passé à `setup(app)` de chaque extension."""

    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database
        self.events = EventBus()
        self.capabilities = CapabilityRegistry()
        self.widgets = WidgetRegistry()
        self.decisions = DecisionRegistry()
        for decision in builtin_decisions():
            self.decisions.register(decision)
        self.backend = JevBackend(settings.typesafe_api_key)
        self.engine = DecisionEngine(self.decisions, self.backend, database)
        self.prompt = PromptSections()
        self.commands = CommandCatalog()
        self.http = UrllibHttpClient()
        self.tabs = TabStore(database)
        self.objectives = Objectives(
            database,
            fetcher=http_fetcher(self.http),
            writer=self._report,
            judge=self._judge,
        )
        self.events.subscribe(ObjectiveSignal, self.objectives.on_signal)
        self.memory = Memories(database, _index(settings), engine=self.engine)
        self.social = Social(database, self.engine)
        self.channel_reader: ChannelReader | None = None
        self._discord_bound = False
        self.llm = OpenAIChatClient(settings.openai_api_key)
        self.prompt.register_section("personality", default_personality, order=0)
        self.prompt.register_section("clock", clock_section(), order=10)
        self.conversation = ConversationService(
            database=database,
            client=self.llm,
            capabilities=self.capabilities,
            prompt=self.prompt,
            settings=settings,
            engine=self.engine,
            widgets=self.widgets,
            memory=self.memory,
            social=self.social,
        )
        register_builtins(self)
        self.plugins = PluginManager(self)
        self._closed = False

    @classmethod
    def open(cls, settings: Settings) -> App:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        database = Database(settings.database_path)
        try:
            applied = database.migrate()
        except Exception:
            database.close()
            raise
        if applied:
            logger.info("Migrations appliquées : %s", ", ".join(applied))
        app = cls(settings, database)
        for module_name in settings.plugins:
            try:
                app.plugins.load(module_name)
            except Exception:
                logger.exception("Extension non chargée : %s", module_name)
        return app

    def bind_discord(
        self,
        *,
        directory: GuildDirectory,
        poster: PollPoster,
        reader: ChannelReader,
    ) -> None:
        """Branche les capacités qui ont besoin du client Discord. Une seule fois."""
        if self._discord_bound:
            return
        self._discord_bound = True
        self.channel_reader = reader
        for capability in discord_capabilities(directory):
            self.capabilities.register(capability)
        self.capabilities.register(poll_capability(poster))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.plugins.unload_all()
        finally:
            self.database.close()

    async def _report(self, prompt: str) -> str:
        completion = await self.llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Tu exécutes une consigne, ce n'est pas une conversation. "
                        "Une phrase, deux max. Uniquement ce qui est demandé. "
                        "Tutoiement, sans emoji, sans commencer par ton nom. "
                        "N'invente aucun fait : s'il manque une preuve, dis-le en une phrase."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        )
        return completion.text

    async def _judge(self, text: str, evidence: str) -> bool:
        verdict = await self.engine.resolve(
            "condition_judge",
            {"condition": text, "evidence": evidence[:2000]},
        )
        return verdict.value is True

    async def aclose(self) -> None:
        self.objectives.scheduler.stop()
        await self.backend.close()
        await self.llm.close()
        self.close()


def _index(settings: Settings) -> VectorIndex:
    opened = open_index(settings.data_dir / "chroma", settings.openai_api_key)
    if opened is None:
        return NullIndex()
    return opened
