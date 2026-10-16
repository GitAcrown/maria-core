"""Une courte ligne quand un outil met plus de deux secondes, effacée avec la réponse."""

import asyncio
import logging
from contextlib import suppress
from types import TracebackType

import discord

from maria_core.conversation.progress import DELAY_S, default_label

logger = logging.getLogger(__name__)


class SlowNotice:
    """À l'entrée, programme l'annonce ; `say` change la phrase ; à la sortie, tout disparaît.

    Elle ne répond au message que si d'autres messages ont suivi : sinon elle se pose simplement
    à la suite, comme la réponse finale.
    """

    def __init__(
        self, message: discord.Message, label: str = "", *, delay: float = DELAY_S
    ) -> None:
        self.message = message
        self.label = label or default_label()
        self.delay = delay
        self._timer: asyncio.Task[None] | None = None
        self._sending: asyncio.Future[discord.Message] | None = None
        self.sent_id: int | None = (
            None  # pour que la réponse ne le prenne pas pour un autre message
        )

    async def __aenter__(self) -> "SlowNotice":
        self._timer = asyncio.create_task(self._announce())
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        if self._timer is not None:
            self._timer.cancel()
            with suppress(asyncio.CancelledError):
                await self._timer
        if self._sending is not None:
            try:
                await (await self._sending).delete()
            except discord.HTTPException:
                logger.debug("Annonce d'attente non effacée", exc_info=True)

    async def say(self, label: str) -> None:
        self.label = label
        if self._sending is None:
            return
        try:
            await (await asyncio.shield(self._sending)).edit(content=f"-# {label}")
        except discord.HTTPException:
            logger.debug("Annonce d'attente non modifiée", exc_info=True)

    async def _announce(self) -> None:
        await asyncio.sleep(self.delay)
        channel = self.message.channel
        latest = getattr(channel, "last_message_id", None) == self.message.id
        self._sending = asyncio.ensure_future(
            channel.send(
                f"-# {self.label}",
                reference=None if latest else self.message,
                mention_author=False,
                silent=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        )
        self.sent_id = (await asyncio.shield(self._sending)).id
