"""Un message entre, une réponse sort. Le modèle n'est appelé que si la route le dit."""

import asyncio
import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager, nullcontext
from datetime import UTC, datetime, timedelta
from typing import Protocol

from maria_core.attachments import Digester
from maria_core.capabilities import CapabilityRegistry
from maria_core.config import Settings
from maria_core.conversation.compose import UNAVAILABLE_TEXT, Composed, compose
from maria_core.conversation.context import (
    ContextSource,
    can_stay_silent,
    is_media_only,
    is_reaction_request,
    reaction_target,
    user_entry,
)
from maria_core.conversation.debounce import Debouncer
from maria_core.conversation.model import Action, AudioRef, Inbound, Policy, Reply, Route
from maria_core.conversation.policy import load_policy
from maria_core.conversation.pressure import Pressure
from maria_core.conversation.routing import decide
from maria_core.conversation.turn import TurnInput, TurnRunner
from maria_core.db import Database
from maria_core.decisions.engine import Decider
from maria_core.llm.history import ChannelHistory, HistoryEntry
from maria_core.llm.loop import LoopResult
from maria_core.llm.prompt import PromptSections
from maria_core.llm.types import ChatClient
from maria_core.memory.model import MemoryAsk
from maria_core.memory.service import Memories
from maria_core.memory.text import explicit_fact
from maria_core.profile.service import Profiles
from maria_core.social.service import Social
from maria_core.ui.render import split_message
from maria_core.ui.widgets import WidgetRegistry

__all__ = ["UNAVAILABLE_TEXT", "ConversationService", "DraftDesk"]

logger = logging.getLogger(__name__)

type Thinking = Callable[[], AbstractAsyncContextManager[object]]
type Waiting = Callable[[str], AbstractAsyncContextManager[object]]

_MAX_MESSAGES = 80
_MAX_TOKENS = 10_000
_MAX_AGE = timedelta(hours=1)
_DEBOUNCE_SECONDS = 0.33
_REPLY_MEMORY = 500
_PARALLEL_TURNS = 3
EDIT_WINDOW = timedelta(seconds=60)
_NAMED = frozenset({"name_edge", "name_middle", "name_model"})


class DraftDesk(Protocol):
    """Un « oui » ou un « non » qui répond à un brouillon d'objectif."""

    async def answer(self, message: Inbound) -> bool: ...


class ConversationService:
    def __init__(
        self,
        *,
        database: Database,
        client: ChatClient,
        capabilities: CapabilityRegistry,
        prompt: PromptSections,
        settings: Settings,
        debounce_seconds: float = _DEBOUNCE_SECONDS,
        debouncer: Debouncer | None = None,
        max_messages: int = _MAX_MESSAGES,
        max_tokens: int = _MAX_TOKENS,
        max_age: timedelta = _MAX_AGE,
        engine: Decider | None = None,
        widgets: WidgetRegistry | None = None,
        memory: Memories | None = None,
        social: Social | None = None,
        sources: Sequence[ContextSource] = (),
        profiles: Profiles | None = None,
        digester: Digester | None = None,
    ) -> None:
        self._database = database
        self._client = client
        self._debouncer = debouncer or Debouncer(debounce_seconds)
        self._limits = (max_messages, max_tokens, max_age)
        self._histories: dict[int, ChannelHistory] = {}
        self._replies: dict[int, int] = {}
        self._engine = engine
        self._widgets = widgets or WidgetRegistry()
        self._memory = memory
        self._social = social
        self._profiles = profiles
        self._digester = digester
        self._sources = list(sources)
        self._turns = asyncio.Semaphore(_PARALLEL_TURNS)
        self._locks: dict[int, asyncio.Lock] = {}
        self._pressure = Pressure()
        self._runner = TurnRunner(
            client=client,
            capabilities=capabilities,
            settings=settings,
            database=database,
            prompt=prompt,
            engine=engine,
            slots=profiles,
        )
        self.drafts: DraftDesk | None = None

    def add_source(self, source: ContextSource) -> None:
        self._sources.append(source)

    async def handle(
        self,
        message: Inbound,
        *,
        thinking: Thinking | None = None,
        waiting: Waiting | None = None,
    ) -> Reply | None:
        """Chaque message retenu entre dans le fil ; seul le dernier d'une rafale reçoit réponse."""
        policy = await asyncio.to_thread(load_policy, self._database, message)
        if message.edited:
            return await self._edited(message, policy, thinking, waiting)
        await self._note(message)
        if self.drafts is not None and not message.is_dm and await self.drafts.answer(message):
            self._history(message.channel_id).add(user_entry(message, addressed=True))
            return None
        route = await self._resolve(message, policy)
        if route.action is Action.RESPOND and not self._admits(message, route, policy):
            seen = self._social.room if self._social is not None else None
            logger.info(
                "Réponse retenue (%s) pour %s : %s message(s) de lui et %s dans le salon sur "
                "10 min, trop de réponses déjà données",
                "suivi" if route.reason == "followup" else f"limite {policy.limit}",
                message.author_id,
                seen.from_author(message.channel_id, message.author_id) if seen else 0,
                seen.volume(message.channel_id) if seen else 0,
            )
            route = Route(Action.STORE, "pressure")
        if route.action is Action.IGNORE:
            return None
        if route.action is not Action.RESPOND:
            self._history(message.channel_id).add(user_entry(message, addressed=False))
            await self._quiet(message, route, policy)
            return None
        if self._social is not None:
            self._social.note_addressed(message)
        await self._learn_profile(message)
        self._history(message.channel_id).add(user_entry(message, addressed=True))
        if await self._react_instead(message, route):
            return None
        # Un appel clair (mention, réponse) montre « écrit… » tout de suite ; quand le modèle peut
        # choisir une simple réaction, l'indicateur attend l'appel au modèle.
        early = thinking is not None and not can_stay_silent(message, route)
        async with thinking() if early and thinking is not None else nullcontext():
            latest = await self._debouncer.submit(message)
            if latest is None:
                return None
            return await self._answer(latest, policy, route, None if early else thinking, waiting)

    async def transcribe(self, audio: AudioRef) -> str:
        try:
            data = await audio.load()
            return (await self._client.transcribe(data, filename=audio.filename)).strip()
        except Exception:
            logger.exception("Transcription échouée")
            return ""

    def attach_transcript(self, message: Inbound, transcript: str) -> None:
        """Un vocal transcrit après coup prend sa place dans le fil."""
        history = self._history(message.channel_id)
        entry = user_entry(message.with_text(transcript, transcribed=True), addressed=False)
        history.promote(message.message_id, entry)

    def forget_channel(self, channel_id: int) -> None:
        self._histories.pop(channel_id, None)

    def usage(self, channel_id: int) -> tuple[int, int, int]:
        """Messages et tokens de l'historique du salon, et le plafond."""
        history = self._histories.get(channel_id)
        if history is None:
            return 0, 0, self._limits[1]
        return history.usage()

    def transcript(self, channel_id: int) -> tuple[str, ...]:
        history = self._histories.get(channel_id)
        if history is None:
            return ()
        return tuple(
            f"{item.name or item.role}: {item.content}"
            for item in history.entries()
            if item.content and not item.note
        )

    def remember_reply(self, user_message_id: int, bot_message_id: int) -> None:
        self._replies[user_message_id] = bot_message_id
        while len(self._replies) > _REPLY_MEMORY:
            self._replies.pop(next(iter(self._replies)))

    def note_posted(self, channel_id: int, text: str, *, addressee: str = "") -> None:
        """Un message envoyé hors conversation (rappel, transcription) reste dans le fil."""
        if text.strip():
            self._history(channel_id).add(_assistant_entry(text, addressee=addressee))

    async def _edited(
        self,
        message: Inbound,
        policy: Policy,
        thinking: Thinking | None,
        waiting: Waiting | None,
    ) -> Reply | None:
        history = self._history(message.channel_id)
        if not history.contains(message.message_id):
            return None
        if datetime.now(UTC) - message.created_at > EDIT_WINDOW:
            return None
        route = await self._resolve(message, policy)
        if route.action is Action.IGNORE:
            return None
        addressed = route.action is Action.RESPOND
        history.replace(message.message_id, user_entry(message, addressed=addressed))
        if not addressed or not self._admits(message, route, policy):
            return None
        return await self._answer(message, policy, route, thinking, waiting)

    async def _quiet(self, message: Inbound, route: Route, policy: Policy) -> None:
        if self._social is None:
            return
        if route.action is Action.REACT:
            await self._social.react_now(message, message.message_id)
            return
        await self._social.consider(message, enabled=policy.mode.value != "off")

    async def _react_instead(self, message: Inbound, route: Route) -> bool:
        """Demande de réaction, média seul dans une suite, ou fatigue : un emoji suffit."""
        if self._social is None:
            return False
        if is_reaction_request(message.text):
            await self._social.react_now(message, reaction_target(message), fallback="👍")
            return True
        tired = route.reason in _NAMED and self._social.prefers_emoji(message)
        if (route.reason == "followup" and is_media_only(message)) or tired:
            await self._social.react_now(message, message.message_id)
            return True
        return False

    def _admits(self, message: Inbound, route: Route, policy: Policy) -> bool:
        if self._social is None:
            return True
        room = self._social.room
        return self._pressure.admit(
            message.author_id,
            message.channel_id,
            author_messages=room.from_author(message.channel_id, message.author_id),
            channel_messages=room.volume(message.channel_id),
            limit=policy.limit,
            followup=route.reason == "followup",
        )

    async def _resolve(self, message: Inbound, policy: Policy) -> Route:
        route = decide(message, policy)
        if route.decision is not None and self._engine is not None:
            verdict = await self._engine.resolve(
                route.decision,
                {"text": message.text[:500], "bot_name": route.detail or "Maria"},
            )
            action = {"respond": Action.RESPOND, "react": Action.REACT}.get(
                str(verdict.value), Action.STORE
            )
            route = Route(action, "name_model")
        if route.action is Action.STORE and route.reason not in {"off", "other_bot"}:
            follow = await self._followup(message)
            if follow == "respond":
                route = Route(Action.RESPOND, "followup")
            elif follow == "react":
                route = Route(Action.REACT, "followup")
        logger.info(
            "Message %s salon %s route=%s raison=%s",
            message.message_id,
            message.channel_id,
            route.action.value,
            route.reason,
        )
        return route

    async def _answer(
        self,
        message: Inbound,
        policy: Policy,
        route: Route,
        thinking: Thinking | None,
        waiting: Waiting | None = None,
    ) -> Reply | None:
        history = self._history(message.channel_id)
        files = await self._digest(message)
        if files:
            history.promote(message.message_id, user_entry(message, addressed=True, files=files))
        extras = await self._extras(message)
        data = TurnInput(
            message=message,
            policy=policy,
            history=history,
            model=str(getattr(self._client, "model_name", "") or ""),
            extras=extras,
            silence=can_stay_silent(message, route),
            waiting=waiting,
        )
        lock = self._locks.setdefault(message.channel_id, asyncio.Lock())
        async with lock, self._turns, (thinking or nullcontext)():
            outcome = await self._runner.run(data)
        await asyncio.to_thread(self._log_usage, outcome)
        composed = compose(outcome, self._widgets, message.bot_names)
        if await self._silent(message, composed):
            return None
        ask = await self._ask(message, outcome)
        return self._reply(message, outcome, composed, history, ask)

    async def _silent(self, message: Inbound, composed: Composed) -> bool:
        if composed.text or composed.cards or not (composed.react or composed.skip):
            return False
        logger.info("Silence choisi dans %s", message.channel_id)
        if composed.react and self._social is not None:
            await self._social.react_now(message, message.message_id)
        return True

    async def _extras(self, message: Inbound) -> list[str]:
        found: list[str] = []
        for source in self._sources:
            try:
                found.append(await asyncio.to_thread(source, message))
            except Exception:
                logger.exception("Source de contexte en échec")
        if self._memory is not None:
            found.append(await asyncio.to_thread(self._memory.prompt_for, message))
        return [item for item in found if item]

    async def _digest(self, message: Inbound) -> str:
        """Fichiers et liens du message, lus d'office ; ce qui est illisible est annoncé."""
        if self._digester is None or message.is_dm:
            return ""
        try:
            return await self._digester.build(message)
        except Exception:
            logger.exception("Pièces jointes non lues pour %s", message.message_id)
            return ""

    async def _learn_profile(self, message: Inbound) -> None:
        """Style de la personne et champs dits clairement, sans rien lui demander."""
        if self._profiles is None or message.edited:
            return
        try:
            await asyncio.to_thread(self._profiles.observe, message)
        except Exception:
            logger.exception("Profil non mis à jour pour %s", message.author_id)

    async def _note(self, message: Inbound) -> None:
        if self._social is not None:
            await self._social.note(message)

    async def _followup(self, message: Inbound) -> str:
        if self._social is None:
            return "ignore"
        return await self._social.wants_followup(message)

    async def _ask(self, message: Inbound, outcome: LoopResult) -> MemoryAsk | None:
        if self._memory is None or message.edited or message.is_dm:
            return None
        if "remember_fact" in outcome.tool_names:
            return None
        if not outcome.ok and not explicit_fact(message.text):
            return None
        return await self._memory.observe(message)

    def _reply(
        self,
        message: Inbound,
        outcome: LoopResult,
        composed: Composed,
        history: ChannelHistory,
        ask: MemoryAsk | None,
    ) -> Reply | None:
        text = composed.text
        traced = ask is not None and ask.learned_id is not None
        if ask is not None and not traced:
            text = f"{text}\n\n{ask.text}".strip()
        if not text and not composed.cards:
            return None
        for note in composed.notes:
            history.add(_note_entry(note, message.message_id))
        if outcome.ok and (text or composed.cards):
            spoken = text or "(vue affichée)"
            history.add(
                _assistant_entry(spoken, reply_to=message.message_id, addressee=message.author_name)
            )
        if self._social is not None:
            self._social.note_reply(message, text)
        edit_id = self._replies.get(message.message_id) if message.edited else None
        return Reply(
            chunks=split_message(text) if text else (),
            user_message_id=message.message_id,
            edit_message_id=edit_id,
            reply=edit_id is None,
            cards=composed.cards,
            footer=composed.footer,
            proposal_id=None if ask is None else ask.proposal_id,
            learned_id=None if ask is None else ask.learned_id,
            trace=ask.text if ask is not None and traced else "",
        )

    def _history(self, channel_id: int) -> ChannelHistory:
        history = self._histories.get(channel_id)
        if history is None:
            max_messages, max_tokens, max_age = self._limits
            history = ChannelHistory(
                max_messages=max_messages, max_tokens=max_tokens, max_age=max_age
            )
            self._histories[channel_id] = history
        return history

    def _log_usage(self, outcome: LoopResult) -> None:
        self._database.execute(
            """
            INSERT INTO llm_calls (
                at, purpose, model, input_tokens, output_tokens, duration_ms, ok
            ) VALUES (?, 'conversation', ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(UTC).isoformat(),
                outcome.model,
                outcome.input_tokens,
                outcome.output_tokens,
                outcome.duration_ms,
                1 if outcome.ok else 0,
            ),
        )


def _assistant_entry(
    text: str, *, reply_to: int | None = None, addressee: str = ""
) -> HistoryEntry:
    return HistoryEntry(
        role="assistant",
        content=text,
        created_at=datetime.now(UTC),
        name="MARIA",
        reply_to=reply_to,
        addressee=addressee,
    )


def _note_entry(note: str, reply_to: int) -> HistoryEntry:
    return HistoryEntry(
        role="user",
        content=note,
        created_at=datetime.now(UTC),
        reply_to=reply_to,
        note=True,
    )
