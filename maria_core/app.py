"""Assemble la configuration, la base et les extensions. Ne connaît pas Discord."""

from __future__ import annotations

import logging

from maria_core.attachments import Digester
from maria_core.capabilities import CapabilityRegistry
from maria_core.capabilities.builtin.discord_info import discord_capabilities
from maria_core.capabilities.builtin.polls import PollStore, poll_capability, poll_context
from maria_core.capabilities.http import UrllibHttpClient
from maria_core.capabilities.page import Fetched, fetch_raw
from maria_core.capabilities.ports import ChannelReader, GuildDirectory, PollPoster
from maria_core.capabilities.register import register_builtins
from maria_core.commands import CommandCatalog
from maria_core.config import Settings
from maria_core.conversation.model import Inbound
from maria_core.conversation.persona import clock_section, default_personality
from maria_core.conversation.service import ConversationService
from maria_core.db import Database
from maria_core.db.retention import purge
from maria_core.decisions import DecisionRegistry
from maria_core.decisions.catalog import builtin_decisions
from maria_core.decisions.engine import DecisionEngine
from maria_core.decisions.structured import JevBackend
from maria_core.events import EventBus
from maria_core.llm.client import OpenAIChatClient
from maria_core.llm.prompt import PromptSections
from maria_core.memory import Memories
from maria_core.memory.service import label
from maria_core.memory.summary import MemorySummaries
from maria_core.objectives import Objectives, ObjectiveSignal
from maria_core.objectives.drafts import Drafts
from maria_core.objectives.fetch import brave_searcher, http_fetcher
from maria_core.objectives.report import ReportWriter
from maria_core.plugins import PluginManager
from maria_core.profile import Profiles
from maria_core.profile.tools import profile_capability
from maria_core.social.service import Social
from maria_core.ui import WidgetRegistry
from maria_core.vectors import NullIndex
from maria_core.vectors.chroma import open_index
from maria_core.vectors.index import VectorIndex

logger = logging.getLogger(__name__)

_CONDENSE = (
    "Résume ce lot de messages Discord en 10 lignes maximum. Fidèle, pseudos conservés, "
    "décisions et faits marquants d'abord. Rien d'inventé."
)


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
        self.llm = OpenAIChatClient(settings.openai_api_key)
        self.polls = PollStore(database)
        self.memory = Memories(database, _index(settings), engine=self.engine)
        self.memory_summaries = MemorySummaries(self.llm)
        self.profiles = Profiles(database)
        self.social = Social(database, self.engine)
        self.objectives = Objectives(database, fetcher=http_fetcher(self.http), judge=self._judge)
        self.objectives.pipeline.searcher = brave_searcher(self.http, settings.brave_api_key)
        self.objectives.pipeline.picker = self._pick_price
        self.objectives.matcher.relevance = self._relevant
        self.objectives.is_request = self._is_request
        self.events.subscribe(ObjectiveSignal, self.objectives.on_signal)
        self.channel_reader: ChannelReader | None = None
        self._discord_bound = False
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
            sources=(self._polls, self.profiles.prompt_for),
            profiles=self.profiles,
            digester=Digester(self._fetch_link),
        )
        self.drafts = Drafts(self.objectives, self.engine)
        self.conversation.drafts = self.drafts
        register_builtins(self, condense=self._condense)
        self.capabilities.register(profile_capability(self.profiles))
        self.objectives.pipeline.writer = ReportWriter(
            client=self.llm,
            capabilities=self.capabilities,
            settings=settings,
            database=database,
            widgets=self.widgets,
            profile=self._profile,
            slots=self.profiles,
        )
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

    def housekeeping(self) -> dict[str, int]:
        """Purge des journaux, brouillons expirés, souvenirs à revoir. Hors de la boucle."""
        removed = purge(self.database, self.objectives.now())
        removed["brouillons"] = self.drafts.expire()
        removed["revisions"] = self.memory.housekeeping()
        return removed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.plugins.unload_all()
        finally:
            self.database.close()

    async def aclose(self) -> None:
        self.objectives.scheduler.stop()
        await self.backend.close()
        await self.llm.close()
        self.close()

    async def _judge(self, text: str, evidence: str) -> bool:
        verdict = await self.engine.resolve(
            "condition_judge",
            {"condition": text, "evidence": evidence[:2000]},
        )
        return verdict.value is True

    async def _is_request(self, text: str) -> bool:
        verdict = await self.engine.resolve("objective_request", {"text": text[:400]})
        return verdict.value is True

    async def _relevant(self, name: str, state: object) -> bool:
        """Sans juge disponible, un mot cité suffit ; un sujet flou, lui, ne se devine pas."""
        verdict = await self.engine.resolve(name, dict(state) if isinstance(state, dict) else {})
        if verdict.path == "fallback" and name == "listen_relevance":
            return True
        return verdict.value == "fire"

    async def _pick_price(self, snippets: list[str]) -> int | None:
        verdict = await self.engine.resolve("main_price", {"snippets": snippets})
        try:
            return int(verdict.value)
        except (TypeError, ValueError):
            return None

    async def _condense(self, chunk: str, focus: str) -> str:
        instruction = f"{_CONDENSE} Ce qui compte : {focus}." if focus else _CONDENSE
        completion = await self.llm.complete(
            [{"role": "system", "content": instruction}, {"role": "user", "content": chunk}]
        )
        return completion.text.strip()

    def _profile(self, owner_id: int, guild_id: int | None) -> str:
        facts = self.memory.store.profile(owner_id, limit=4)
        if not facts:
            return ""
        lines = [f"- {label(item, {})} : {item.content}" for item in facts]
        return "PROFIL DU DESTINATAIRE :\n" + "\n".join(lines)

    async def _fetch_link(self, url: str) -> Fetched:
        """Page d'un lien du message : un PDF peut être plus lourd qu'une page web."""
        heavy = url.lower().split("?", 1)[0].endswith(".pdf")
        return await fetch_raw(self.http, url, max_bytes=10_000_000 if heavy else 2_000_000)

    def _polls(self, message: Inbound) -> str:
        if message.guild_id is None:
            return ""
        return poll_context(self.polls, message.channel_id)


def _index(settings: Settings) -> VectorIndex:
    opened = open_index(settings.data_dir / "chroma", settings.openai_api_key)
    if opened is None:
        return NullIndex()
    return opened
