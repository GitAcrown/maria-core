"""Un « oui » ou un « non » dans le salon valide ou annule le dernier brouillon. Sans GPT."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from maria_core.conversation.model import Inbound
from maria_core.decisions.engine import Decider
from maria_core.objectives.model import DRAFT_TTL, StaleObjective
from maria_core.objectives.runtime import Objectives
from maria_core.objectives.schedule import describe
from maria_core.objectives.tools import apply

logger = logging.getLogger(__name__)

_MAX_CHARS = 80

type Reactor = Callable[[int, int, str], Awaitable[bool]]


class Drafts:
    def __init__(self, objectives: Objectives, engine: Decider | None) -> None:
        self._objectives = objectives
        self._engine = engine
        self.reactor: Reactor | None = None

    async def answer(self, message: Inbound) -> bool:
        """True si le message a tranché un brouillon (le message ne reçoit pas d'autre réponse)."""
        text = message.text.strip()
        if not text or len(text) > _MAX_CHARS or message.files or message.images:
            return False
        since = self._objectives.now() - DRAFT_TTL
        draft = await asyncio.to_thread(
            self._objectives.store.latest_draft, message.author_id, message.channel_id, since
        )
        if draft is None or self._engine is None:
            return False
        summary = f"{draft.title} — {describe(draft.trigger)}"
        verdict = await self._engine.resolve("draft_reply", {"text": text, "draft": summary})
        if verdict.value not in {"accept", "reject"}:
            return False
        op = "confirm" if verdict.value == "accept" else "cancel"
        try:
            await asyncio.to_thread(apply, self._objectives, draft, {"op": op})
        except (StaleObjective, ValueError):
            logger.info("Brouillon %s déjà traité", draft.id)
            return False
        if self.reactor is not None:
            emoji = "✅" if op == "confirm" else "❌"
            await self.reactor(message.channel_id, message.message_id, emoji)
        return True

    def expire(self) -> int:
        now = self._objectives.now()
        return self._objectives.store.expire_drafts(now - DRAFT_TTL, now)
