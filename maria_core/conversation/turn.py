"""Un tour avec le modèle : prompt, outils, garde-fous, nouvel essai sans image."""

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace

from maria_core.capabilities import CapabilityRegistry, Context, Result, Risk
from maria_core.capabilities.runner import SlotSource, available, invoke
from maria_core.config import Settings
from maria_core.conversation.calc import HINT as CALC_HINT
from maria_core.conversation.calc import needs_calculation
from maria_core.conversation.context import (
    FOLLOWUP_GUIDE,
    SILENCE_GUIDE,
    focus_note,
    turn_header,
)
from maria_core.conversation.model import Inbound, Policy
from maria_core.db import Database
from maria_core.decisions.engine import Decider
from maria_core.llm.history import ChannelHistory
from maria_core.llm.loop import LoopResult, complete_turn
from maria_core.llm.prompt import PromptSections
from maria_core.llm.schema import openai_tool
from maria_core.llm.types import ChatClient, ToolCall, ToolChoice

logger = logging.getLogger(__name__)

_IMAGE_ERRORS = ("image", "invalid_image")
_SEARCH = "search_web"
_VERIFY_HINT = (
    "[VÉRIFICATION] Ta réponse précédente donnait des faits d'actualité sans les avoir "
    "vérifiés. Appelle l'outil adapté (recherche web, météo, score…) puis réponds à nouveau, "
    "avec le même ton qu'avant."
)


@dataclass(slots=True)
class TurnInput:
    message: Inbound
    policy: Policy
    history: ChannelHistory
    model: str
    extras: Sequence[str] = ()
    silence: bool = False
    followup: bool = False
    files: str = ""
    deny: frozenset[str] = field(default_factory=frozenset)
    announce: Callable[[Sequence[ToolCall]], Awaitable[None]] | None = None


class TurnRunner:
    def __init__(
        self,
        *,
        client: ChatClient,
        capabilities: CapabilityRegistry,
        settings: Settings,
        database: Database,
        prompt: PromptSections,
        engine: Decider | None,
        slots: SlotSource | None = None,
    ) -> None:
        self._client = client
        self._capabilities = capabilities
        self._settings = settings
        self._database = database
        self._prompt = prompt
        self._engine = engine
        self._slots = slots

    async def run(self, data: TurnInput) -> LoopResult:
        choice = await self._choice(data.message)
        if needs_calculation(data.message.text) and "calculate" in self._capabilities:
            data = replace(data, extras=(*data.extras, CALC_HINT))
            choice = "required"
        outcome = await self._once(data, choice)
        outcome = await self._verified(data, outcome)
        if not outcome.ok and any(word in outcome.error.lower() for word in _IMAGE_ERRORS):
            logger.warning("Image refusée par le modèle, nouvel essai sans image")
            data.history.without_images()
            outcome = await self._once(data, choice)
        return outcome

    async def _verified(self, data: TurnInput, outcome: LoopResult) -> LoopResult:
        """Un fait d'actualité donné sans outil est revérifié une fois, sans toucher au ton."""
        if self._engine is None or not outcome.ok or outcome.records or not outcome.text:
            return outcome
        question = data.message.text[:400]
        state = {"question": question, "answer": outcome.text[:600], "tools": 0}
        try:
            verdict = await self._engine.resolve("claim_check", state)
        except Exception:
            logger.exception("Décision claim_check en échec")
            return outcome
        if verdict.value != "needs_check":
            return outcome
        logger.info("Réponse sans outil revérifiée pour le message %s", data.message.message_id)
        hinted = replace(data, extras=(*data.extras, _VERIFY_HINT))
        again = await self._once(hinted, "required")
        if not again.ok or not again.records or not again.text:
            return outcome
        return replace(
            again,
            input_tokens=again.input_tokens + outcome.input_tokens,
            output_tokens=again.output_tokens + outcome.output_tokens,
            calls=again.calls + outcome.calls,
            duration_ms=again.duration_ms + outcome.duration_ms,
        )

    def system(self) -> str:
        """Identique d'un message à l'autre : l'API en garde le début en cache."""
        return self._prompt.render()

    def volatile(self, data: TurnInput) -> str:
        """Heure, repères, mémoire : ce qui change à chaque tour, donné après l'historique."""
        parts = [self._prompt.render_volatile()]
        parts.append(turn_header(data.message, model=data.model))
        parts.extend(item.strip() for item in data.extras if item and item.strip())
        if data.followup:
            parts.append(FOLLOWUP_GUIDE)  # plus sobre que le guide du silence : peu d'emojis
        elif data.silence:
            parts.append(SILENCE_GUIDE)
        return "\n\n".join(part for part in parts if part)

    async def _once(self, data: TurnInput, choice: ToolChoice) -> LoopResult:
        tools = [
            openai_tool(item)
            for item in available(self._capabilities, self._settings)
            if item.name not in data.deny
        ]
        messages = list(data.history.api_messages())
        messages.append({"role": "system", "content": self.volatile(data)})
        messages.append(focus_note(data.message, data.files))
        guard = _SearchGuard()
        context = _context(data.message)

        async def execute(call: ToolCall) -> Result:
            refused = guard.refuse(call)
            if refused is not None:
                return refused
            result = await invoke(
                self._capabilities,
                self._settings,
                context,
                call,
                database=self._database,
                slots=self._slots,
            )
            guard.saw(call, result)
            return result

        return await complete_turn(
            self._client,
            messages,
            system=self.system(),
            tools=tools,
            execute=execute,
            first_choice=choice if tools else "auto",
            parallel_safe=self._parallel_safe,
            announce=data.announce,
        )

    def _parallel_safe(self, name: str) -> bool:
        """Lire et chercher peuvent se faire en même temps ; écrire ou exécuter, jamais."""
        if name not in self._capabilities:
            return False
        return self._capabilities.get(name).risk in {Risk.READ, Risk.EXTERNAL}

    async def _choice(self, message: Inbound) -> ToolChoice:
        """Une demande factuelle claire part d'abord sur un outil, jamais de mémoire."""
        if self._engine is None or not message.text.strip():
            return "auto"
        try:
            verdict = await self._engine.resolve("intent", {"text": message.text[:400]})
        except Exception:
            logger.exception("Décision intent en échec")
            return "auto"
        return "required" if verdict.value == "web" else "auto"


class _SearchGuard:
    """Une recherche web par message ; une seconde seulement si la première n'a rien donné."""

    def __init__(self) -> None:
        self._done = 0
        self._empty = False
        self._running = False

    def refuse(self, call: ToolCall) -> Result | None:
        if call.name != _SEARCH:
            return None
        busy = self._running or (self._done > 0 and not (self._empty and self._done < 2))
        if not busy:
            self._running = True
            return None
        return Result(
            ok=False,
            data={},
            error="Une recherche suffit : utilise ces résultats ou read_web_page.",
        )

    def saw(self, call: ToolCall, result: Result) -> None:
        if call.name != _SEARCH:
            return
        self._running = False
        self._done += 1
        self._empty = not result.ok or not result.data.get("results")


def _context(message: Inbound) -> Context:
    return Context(
        user_id=message.author_id,
        guild_id=message.guild_id,
        channel_id=message.channel_id,
        message_id=message.message_id,
        is_owner=message.author_is_owner,
        is_moderator=message.author_is_moderator,
        text=message.text,
        author_name=message.author_name,
    )
