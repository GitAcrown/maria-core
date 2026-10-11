"""Reçoit les messages Discord et poste la réponse du service de conversation."""

import asyncio
import logging

import discord
from discord.ext import commands

from maria_core.app import App
from maria_core.conversation import ConversationService
from maria_core.conversation.model import Inbound, Reply
from maria_core.discord.inbound import inbound_from_message
from maria_core.discord.memory_view import ProposalView
from maria_core.discord.tabs import TabView
from maria_core.objectives.signals import ObjectiveSignal

logger = logging.getLogger(__name__)


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self._guard(message, edited=False)

    @commands.Cog.listener()
    async def on_message_edit(
        self,
        before: discord.Message,
        after: discord.Message,
    ) -> None:
        if (before.content or "") == (after.content or ""):
            return
        await self._guard(after, edited=True)

    async def _guard(self, message: discord.Message, *, edited: bool) -> None:
        try:
            await self._incoming(message, edited=edited)
        except Exception:
            logger.exception("Message %s laissé de côté", message.id)

    async def _incoming(self, message: discord.Message, *, edited: bool) -> None:
        inbound = await inbound_from_message(message, bot=self.bot, edited=edited)
        if inbound is None:
            return
        if not edited:
            await _publish_signal(self.bot, inbound)
        reply = await _service(self.bot).handle(inbound, thinking=message.channel.typing)
        if reply is None:
            return
        await self._publish(message, reply)

    async def _publish(self, message: discord.Message, reply: Reply) -> None:
        if reply.edit_message_id is not None and len(reply.chunks) == 1:
            edited = await _try_edit(message, reply)
            if edited:
                return
        view, tab_id = await _tab_view(self.bot, message.channel.id, reply)
        if reply.proposal_id is not None:
            view, tab_id = ProposalView(reply.proposal_id), None
        first, last = await _send_chunks(message, reply, view)
        if first is not None:
            _service(self.bot).remember_reply(reply.user_message_id, first)
        if tab_id is not None and last is not None:
            await asyncio.to_thread(self.bot.app.tabs.attach, tab_id, last)
        if reply.proposal_id is not None and last is not None:
            await asyncio.to_thread(
                self.bot.app.memory.store.attach_reply,
                reply.proposal_id,
                last,
            )


async def _try_edit(message: discord.Message, reply: Reply) -> bool:
    if reply.edit_message_id is None:
        return False
    try:
        existing = await message.channel.fetch_message(reply.edit_message_id)
        await existing.edit(content=reply.chunks[0])
    except discord.HTTPException:
        logger.warning("Réponse %s impossible à modifier", reply.edit_message_id)
        return False
    return True


async def _send_chunks(
    message: discord.Message,
    reply: Reply,
    view: discord.ui.View | None,
) -> tuple[int | None, int | None]:
    """`message` peut être plus ancien que celui auquel on répond après une rafale."""
    anchor = _anchor(message, reply)
    first: int | None = None
    last: int | None = None
    final = len(reply.chunks) - 1
    for index, chunk in enumerate(reply.chunks):
        try:
            sent = await message.channel.send(
                chunk,
                reference=anchor if index == 0 else None,
                view=view if index == final else None,
            )
        except discord.HTTPException:
            logger.warning("Envoi refusé dans le salon %s", message.channel.id)
            return first, last
        if first is None:
            first = sent.id
        last = sent.id
    return first, last


async def _tab_view(
    bot: commands.Bot,
    channel_id: int,
    reply: Reply,
) -> tuple[discord.ui.View | None, str | None]:
    if not reply.tabs:
        return None, None
    app = getattr(bot, "app", None)
    if not isinstance(app, App):
        return None, None
    saved = await asyncio.to_thread(app.tabs.save, channel_id, reply.tabs)
    return TabView(app.tabs, saved), saved.id


def _anchor(message: discord.Message, reply: Reply) -> discord.MessageReference | None:
    if not reply.reply:
        return None
    return discord.MessageReference(
        message_id=reply.user_message_id,
        channel_id=message.channel.id,
        guild_id=message.guild.id if message.guild else None,
        fail_if_not_exists=False,
    )


async def _publish_signal(bot: commands.Bot, inbound: Inbound) -> None:
    app = getattr(bot, "app", None)
    if not isinstance(app, App):
        return
    app.events.publish_soon(
        ObjectiveSignal(
            kind="message",
            key=f"message:{inbound.message_id}",
            channel_id=inbound.channel_id,
            guild_id=inbound.guild_id,
            user_id=inbound.author_id,
            text=inbound.text,
            reply_to_bot=inbound.reply_to_bot,
        )
    )


def _service(bot: commands.Bot) -> ConversationService:
    app = getattr(bot, "app", None)
    if not isinstance(app, App):
        raise RuntimeError("Le bot n'est pas relié à une application.")
    return app.conversation
