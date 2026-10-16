"""« Je cherche sur le web… » : une courte ligne si un outil met plus de quelques secondes."""

import asyncio
import logging
from contextlib import suppress
from types import TracebackType

import discord

from maria_core.conversation.progress import DELAY_S

logger = logging.getLogger(__name__)


class SlowToolNotice:
    """À l'entrée, programme l'annonce ; à la sortie, l'annule ou efface celle qui est partie."""

    def __init__(self, message: discord.Message, label: str, *, delay: float = DELAY_S) -> None:
        self.message = message
        self.label = label
        self.delay = delay
        self._timer: asyncio.Task[None] | None = None
        self._sending: asyncio.Future[discord.Message] | None = None

    async def __aenter__(self) -> "SlowToolNotice":
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

    async def _announce(self) -> None:
        await asyncio.sleep(self.delay)
        self._sending = asyncio.ensure_future(
            self.message.channel.send(
                f"-# {self.label}",
                reference=self.message,
                mention_author=False,
                silent=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        )
        await asyncio.shield(self._sending)
