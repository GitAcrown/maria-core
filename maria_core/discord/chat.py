"""Reçoit les messages Discord et poste la réponse du service de conversation."""

import asyncio
import logging
import re

import discord
from discord.ext import commands

from maria_core.app import App
from maria_core.conversation.model import Inbound, Reply
from maria_core.discord.inbound import inbound_from_message
from maria_core.discord.layout import build_views, quiet_links
from maria_core.discord.learned_view import LearnedView
from maria_core.discord.memory_view import ProposalView
from maria_core.discord.voice import prepare_voice
from maria_core.discord.waiting import SlowNotice
from maria_core.objectives.signals import ObjectiveSignal

logger = logging.getLogger(__name__)

SILENT = discord.AllowedMentions.none()
_LIMIT = 2000


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot, app: App) -> None:
        self.bot = bot
        self.app = app

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        await self._guard(message, edited=False)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if (before.content or "") == (after.content or ""):
            return
        await self._guard(after, edited=True)

    @commands.Cog.listener()
    async def on_typing(self, channel: object, user: discord.abc.User, _when: object) -> None:
        if not getattr(user, "bot", False) and hasattr(channel, "id"):
            self.app.social.typing(int(getattr(channel, "id", 0)), user.id)

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
            _publish_signal(self.app, inbound, message.jump_url)
            inbound = await prepare_voice(self.app, message, inbound)
        notices: list[SlowNotice] = []

        def waiting() -> SlowNotice:
            notices.append(SlowNotice(message))
            return notices[-1]

        reply = await self.app.conversation.handle(
            inbound, thinking=message.channel.typing, waiting=waiting
        )
        if reply is not None:
            own = {notice.sent_id for notice in notices if notice.sent_id is not None}
            await self._publish(message, reply, own)

    async def _publish(
        self, message: discord.Message, reply: Reply, own: set[int] | None = None
    ) -> None:
        if reply.edit_message_id is not None and await _try_edit(message, reply):
            return
        anchor = reply_anchor(message, reply, own or set())
        extra = _extra_view(reply)
        if reply.cards:
            first, last = await _send_views(message.channel, reply, anchor)
            if extra is not None:
                last = await _send_extra(message.channel, extra, reply.trace) or last
        else:
            first, last = await _send_chunks(message.channel, reply, anchor, extra)
        if first is not None:
            self.app.conversation.remember_reply(reply.user_message_id, first)
        if reply.proposal_id is not None and last is not None:
            await _attach(self.app, reply.proposal_id, last)
        if reply.learned_id is not None and last is not None:
            await asyncio.to_thread(self.app.memory.learned.attach_reply, reply.learned_id, last)


async def _send_views(
    channel: discord.abc.Messageable,
    reply: Reply,
    anchor: discord.MessageReference | None,
) -> tuple[int | None, int | None]:
    first: int | None = None
    last: int | None = None
    for index, view in enumerate(
        build_views(intro=reply.text, cards=reply.cards, outro=reply.footer)
    ):
        try:
            sent = await channel.send(
                view=view, reference=anchor if index == 0 else None, allowed_mentions=SILENT
            )
        except discord.HTTPException as exc:
            logger.warning("Vue refusée par Discord (%s), repli en texte", exc.status)
            return await _fallback_text(channel, reply, anchor)
        first = first or sent.id
        last = sent.id
    return first, last


async def _fallback_text(
    channel: discord.abc.Messageable, reply: Reply, anchor: discord.MessageReference | None
) -> tuple[int | None, int | None]:
    body = "\n\n".join([reply.text, *(card.as_text() for card in reply.cards)]).strip()
    fallback = Reply(
        chunks=(body[:_LIMIT],),
        user_message_id=reply.user_message_id,
        edit_message_id=None,
        reply=reply.reply,
        footer=reply.footer,
    )
    return await _send_chunks(channel, fallback, anchor, None)


async def _send_chunks(
    channel: discord.abc.Messageable,
    reply: Reply,
    anchor: discord.MessageReference | None,
    view: discord.ui.View | None,
) -> tuple[int | None, int | None]:
    chunks = [quiet_links(chunk) for chunk in reply.chunks]
    for line in (reply.footer, reply.trace):
        if not line:
            continue
        if chunks and len(chunks[-1]) + len(line) + 1 <= _LIMIT:
            chunks[-1] = f"{chunks[-1]}\n{quiet_links(line)}"
        else:
            chunks.append(quiet_links(line))
    first: int | None = None
    last: int | None = None
    final = len(chunks) - 1
    for index, chunk in enumerate(chunks):
        try:
            kwargs: dict[str, object] = {"reference": anchor if index == 0 else None}
            if view is not None and index == final:
                kwargs["view"] = view
            sent = await channel.send(chunk, allowed_mentions=SILENT, **kwargs)
        except discord.HTTPException:
            logger.warning("Envoi refusé dans le salon %s", getattr(channel, "id", "?"))
            return first, last
        first = first or sent.id
        last = sent.id
    return first, last


async def _send_extra(
    channel: discord.abc.Messageable, view: discord.ui.View, text: str = ""
) -> int | None:
    try:
        sent = await channel.send(text or "-# Retenir ?", view=view, allowed_mentions=SILENT)
    except discord.HTTPException:
        return None
    return sent.id


async def _try_edit(message: discord.Message, reply: Reply) -> bool:
    """Réédite la réponse seulement si elle est encore le dernier message du salon."""
    if reply.edit_message_id is None or reply.cards or len(reply.chunks) != 1:
        return False
    if getattr(message.channel, "last_message_id", None) != reply.edit_message_id:
        return False
    body = quiet_links(f"{reply.chunks[0]}\n{reply.footer}".strip())
    try:
        existing = await message.channel.fetch_message(reply.edit_message_id)
        await existing.edit(content=body[:_LIMIT], allowed_mentions=SILENT)
    except discord.HTTPException:
        logger.warning("Réponse %s impossible à modifier", reply.edit_message_id)
        return False
    return True


def _extra_view(reply: Reply) -> discord.ui.View | None:
    if reply.learned_id is not None:
        return LearnedView(reply.learned_id)
    if reply.proposal_id is not None:
        return ProposalView(reply.proposal_id)
    return None


async def _attach(app: App, proposal_id: int, message_id: int) -> None:
    await asyncio.to_thread(app.memory.store.attach_reply, proposal_id, message_id)


def reply_anchor(
    message: discord.Message, reply: Reply, own: set[int]
) -> discord.MessageReference | None:
    """Reply seulement si d'autres ont écrit depuis : la ligne d'attente de MARIA ne compte pas."""
    if not reply.reply or message.guild is None:
        return None
    last = getattr(message.channel, "last_message_id", None)
    if last == reply.user_message_id or last in own:
        return None
    return discord.MessageReference(
        message_id=reply.user_message_id,
        channel_id=message.channel.id,
        guild_id=message.guild.id,
        fail_if_not_exists=False,
    )


def _publish_signal(app: App, inbound: Inbound, url: str) -> None:
    app.events.publish_soon(
        ObjectiveSignal(
            kind="message",
            key=f"message:{inbound.message_id}",
            channel_id=inbound.policy_channel_id,
            guild_id=inbound.guild_id,
            user_id=inbound.author_id,
            text=inbound.text,
            reply_to_bot=inbound.reply_to_bot,
            author_name=inbound.author_name,
            url=url,
            message_id=inbound.message_id,
            author_is_bot=inbound.author_is_bot,
            mentioned_ids=inbound.mentioned_ids,
            has_link=_LINK.search(inbound.text) is not None,
            media=_media_kinds(inbound),
        )
    )


_LINK = re.compile(r"https?://\S+", re.IGNORECASE)


def _media_kinds(inbound: Inbound) -> tuple[str, ...]:
    """Ce que le message contient : image, vidéo, son, fichier."""
    found: list[str] = []
    if inbound.images:
        found.append("image")
    if inbound.audio is not None:
        found.append("audio")
    for item in inbound.files:
        kind = str(item.content_type or "").split("/")[0]
        found.append(kind if kind in {"video", "audio", "image"} else "file")
    return tuple(dict.fromkeys(found))
