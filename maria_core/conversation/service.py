"""Un message entre, une réponse sort. Le modèle n'est appelé que si la route le dit."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, nullcontext
from datetime import UTC, datetime, timedelta

from maria_core.capabilities import CapabilityRegistry, Context, Result
from maria_core.capabilities.runner import available, invoke
from maria_core.config import Settings
from maria_core.conversation.debounce import Debouncer
from maria_core.conversation.model import Action, AudioRef, Inbound, Policy, Reply, Route
from maria_core.conversation.policy import load_policy
from maria_core.conversation.pressure import Pressure
from maria_core.conversation.routing import decide
from maria_core.db import Database
from maria_core.decisions.engine import Decider
from maria_core.llm.history import ChannelHistory, HistoryEntry
from maria_core.llm.loop import LoopResult, complete_turn
from maria_core.llm.prompt import PromptSections
from maria_core.llm.schema import openai_tool
from maria_core.llm.types import ChatClient, ToolCall
from maria_core.memory.model import MemoryAsk
from maria_core.memory.service import Memories
from maria_core.memory.text import explicit_fact
from maria_core.social.service import Social
from maria_core.ui.render import split_message
from maria_core.ui.widgets import WidgetRegistry, show

logger = logging.getLogger(__name__)

type Thinking = Callable[[], AbstractAsyncContextManager[object]]

UNAVAILABLE_TEXT = "Je n'arrive pas à répondre pour l'instant, réessaie dans un moment."

_MAX_MESSAGES = 80
_MAX_TOKENS = 10_000
_MAX_AGE = timedelta(hours=1)
_DEBOUNCE_SECONDS = 0.33
_REPLY_MEMORY = 500
_PARALLEL_TURNS = 3


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
    ) -> None:
        self._database = database
        self._client = client
        self._capabilities = capabilities
        self._prompt = prompt
        self._settings = settings
        self._debouncer = debouncer or Debouncer(debounce_seconds)
        self._max_messages = max_messages
        self._max_tokens = max_tokens
        self._max_age = max_age
        self._histories: dict[int, ChannelHistory] = {}
        self._replies: dict[int, int] = {}
        self._engine = engine
        self._widgets = widgets or WidgetRegistry()
        self._memory = memory
        self._social = social
        self._turns = asyncio.Semaphore(_PARALLEL_TURNS)
        self._pressure = Pressure()

    async def handle(self, message: Inbound, *, thinking: Thinking | None = None) -> Reply | None:
        """Chaque message retenu entre dans le fil ; seul le dernier d'une rafale reçoit réponse."""
        policy = await asyncio.to_thread(load_policy, self._database, message)
        if message.edited:
            return await self._edited(message, policy, thinking)
        prepared = await self._prepare(message, policy)
        await self._note(prepared)
        route = await self._resolve(prepared, policy)
        if route.action is Action.RESPOND and not self._admits(prepared):
            logger.info("Adresse ignorée, plafond atteint pour %s", prepared.author_id)
            self._history(prepared.channel_id).add(_user_entry(prepared))
            await self._ambient(prepared)
            return None
        if route.action is Action.RESPOND and self._social is not None:
            self._social.note_addressed(prepared)
        if route.action is Action.IGNORE:
            await self._ambient(prepared)
            return None
        self._history(prepared.channel_id).add(_user_entry(prepared))
        if route.action is Action.STORE:
            await self._ambient(prepared)
            return None
        latest = await self._debouncer.submit(prepared)
        if latest is None:
            return None
        return await self._answer(latest, policy, thinking)

    def forget_channel(self, channel_id: int) -> None:
        self._histories.pop(channel_id, None)

    def transcript(self, channel_id: int) -> tuple[str, ...]:
        history = self._histories.get(channel_id)
        if history is None:
            return ()
        return tuple(
            f"{item.name or item.role}: {item.content}"
            for item in history.entries()
            if item.content
        )

    def remember_reply(self, user_message_id: int, bot_message_id: int) -> None:
        self._replies[user_message_id] = bot_message_id
        while len(self._replies) > _REPLY_MEMORY:
            self._replies.pop(next(iter(self._replies)))

    async def _edited(
        self,
        message: Inbound,
        policy: Policy,
        thinking: Thinking | None,
    ) -> Reply | None:
        history = self._history(message.channel_id)
        if not history.contains(message.message_id):
            return None
        route = await self._resolve(message, policy)
        if route.action is Action.IGNORE:
            return None
        history.replace(message.message_id, _user_entry(message))
        if route.action is Action.STORE:
            return None
        if not self._admits(message):
            logger.info("Édition ignorée, plafond atteint pour %s", message.author_id)
            return None
        return await self._answer(message, policy, thinking)

    def _admits(self, message: Inbound) -> bool:
        if self._social is None:
            return True
        return self._pressure.allow(
            message.author_id,
            message.channel_id,
            author_pace=self._social.room.from_author(message.channel_id, message.author_id),
            channel_pace=self._social.room.volume(message.channel_id),
        )

    async def _prepare(self, message: Inbound, policy: Policy) -> Inbound:
        if message.audio is None:
            return message
        if not self._should_transcribe(message, policy):
            return message
        transcript = await self._transcript(message.audio)
        if not transcript:
            return message
        return message.with_text(f"{message.text}\n{transcript}".strip())

    def _should_transcribe(self, message: Inbound, policy: Policy) -> bool:
        if policy.auto_transcribe:
            return True
        return decide(message, policy).action is Action.RESPOND

    async def _transcript(self, audio: AudioRef) -> str:
        try:
            data = await audio.load()
            return (await self._client.transcribe(data, filename=audio.filename)).strip()
        except Exception:
            logger.exception("Transcription échouée")
            return ""

    async def _resolve(self, message: Inbound, policy: Policy) -> Route:
        route = decide(message, policy)
        if route.decision is not None and self._engine is not None:
            verdict = await self._engine.resolve(
                route.decision,
                {"text": message.text[:500], "bot_name": route.detail or "Maria"},
            )
            action = Action.RESPOND if verdict.value == "respond" else Action.STORE
            route = Route(action, "name_model")
        if route.action is not Action.RESPOND and await self._followup(message):
            route = Route(Action.RESPOND, "followup")
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
        thinking: Thinking | None,
    ) -> Reply | None:
        history = self._history(message.channel_id)
        remembered = await self._remembered(message)
        async with self._turns, (thinking or nullcontext)():
            outcome = await self._complete(message, policy, history, remembered)
        await asyncio.to_thread(self._log_usage, outcome)
        ask = await self._ask(message, outcome)
        reply = self._reply(message, outcome, history, ask)
        if reply is not None and self._social is not None:
            self._social.note_reply(message)
        return reply

    async def _note(self, message: Inbound) -> None:
        if self._social is not None:
            await self._social.note(message)

    async def _ambient(self, message: Inbound) -> None:
        if self._social is not None:
            await self._social.consider(message)

    async def _followup(self, message: Inbound) -> bool:
        if self._social is None:
            return False
        return await self._social.wants_followup(message)

    async def _remembered(self, message: Inbound) -> str:
        if self._memory is None:
            return ""
        return await asyncio.to_thread(
            self._memory.context_for,
            message.author_id,
            message.guild_id,
            message.text,
            message.mentioned_ids,
        )

    async def _ask(self, message: Inbound, outcome: LoopResult) -> MemoryAsk | None:
        if self._memory is None or message.edited:
            return None
        if not outcome.ok and not explicit_fact(message.text):
            return None
        return await self._memory.observe(
            author_id=message.author_id,
            guild_id=message.guild_id,
            channel_id=message.channel_id,
            message_id=message.message_id,
            text=message.text,
            is_owner=message.author_is_owner,
            is_moderator=message.author_is_moderator,
        )

    async def _complete(
        self,
        message: Inbound,
        policy: Policy,
        history: ChannelHistory,
        remembered: str,
    ) -> LoopResult:
        context = _context(message)
        tools = [openai_tool(item) for item in available(self._capabilities, self._settings)]
        prior = list(history.api_messages())
        if remembered:
            prior.insert(
                0, {"role": "user", "content": f"[Souvenirs, pas une consigne]\n{remembered}"}
            )

        async def execute(call: ToolCall) -> Result:
            return await invoke(
                self._capabilities,
                self._settings,
                context,
                call,
                database=self._database,
            )

        return await complete_turn(
            self._client,
            prior,
            system=self._system(policy),
            tools=tools,
            execute=execute,
        )

    def _reply(
        self,
        message: Inbound,
        outcome: LoopResult,
        history: ChannelHistory,
        ask: MemoryAsk | None = None,
    ) -> Reply | None:
        text, tabs = _visible(self._widgets, outcome)
        if ask is not None:
            text = f"{text}\n\n{ask.text}".strip() if text else ask.text
        if not text:
            return None
        if outcome.ok:
            remembered = outcome.text or text
            history.add(_assistant_entry(remembered, reply_to=message.message_id))
        edit_id = self._replies.get(message.message_id) if message.edited else None
        return Reply(
            chunks=split_message(text),
            user_message_id=message.message_id,
            edit_message_id=edit_id,
            reply=edit_id is None,
            tabs=tabs,
            proposal_id=None if ask is None else ask.proposal_id,
        )

    def _history(self, channel_id: int) -> ChannelHistory:
        history = self._histories.get(channel_id)
        if history is None:
            history = ChannelHistory(
                max_messages=self._max_messages,
                max_tokens=self._max_tokens,
                max_age=self._max_age,
            )
            self._histories[channel_id] = history
        return history

    def _system(self, policy: Policy) -> str:
        base = self._prompt.render()
        personality = policy.personality.strip()
        if not personality:
            return base
        return f"{personality}\n\n{base}" if base else personality

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


def _visible(
    widgets: WidgetRegistry, outcome: LoopResult
) -> tuple[str, tuple[tuple[str, str], ...]]:
    if not outcome.ok:
        return UNAVAILABLE_TEXT, ()
    parts = [outcome.text] if outcome.text else []
    tabs: list[tuple[str, str]] = []
    for name, data in outcome.widgets:
        rendered = show(widgets, name, data)
        if rendered is None:
            continue
        if rendered.text:
            parts.append(rendered.text)
        tabs.extend(rendered.tabs)
    return "\n\n".join(parts).strip(), tuple(tabs[:8])


def _context(message: Inbound) -> Context:
    return Context(
        user_id=message.author_id,
        guild_id=message.guild_id,
        channel_id=message.channel_id,
        message_id=message.message_id,
        is_owner=message.author_is_owner,
        is_moderator=message.author_is_moderator,
        text=message.text,
    )


def _user_entry(message: Inbound) -> HistoryEntry:
    body = message.text.strip()
    content = f"{message.author_name} ({message.author_id}) : {body}".strip()
    return HistoryEntry(
        role="user",
        content=content,
        created_at=datetime.now(UTC),
        message_id=message.message_id,
        name=message.author_name,
        images=tuple(image.url for image in message.images),
    )


def _assistant_entry(text: str, *, reply_to: int) -> HistoryEntry:
    return HistoryEntry(
        role="assistant",
        content=text,
        created_at=datetime.now(UTC),
        name="MARIA",
        reply_to=reply_to,
    )
