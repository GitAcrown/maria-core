"""Envoie un objectif : ping du propriétaire, réponse à la demande d'origine, pied discret."""

import logging
import re

import discord
from discord.ext import commands

from maria_core.app import App
from maria_core.discord.layout import build_views, quiet_links
from maria_core.objectives.model import Objective
from maria_core.objectives.pipeline import Delivery
from maria_core.ui.render import split_message

logger = logging.getLogger(__name__)

_MENTION = re.compile(r"<@!?\d+>\s*")


class DiscordCourier:
    def __init__(self, bot: commands.Bot) -> None:
        self._bot = bot

    async def send(self, objective: Objective, delivery: Delivery) -> None:
        destination = await self._destination(objective)
        dm = isinstance(destination, discord.User | discord.Member | discord.DMChannel)
        elsewhere = delivery.trigger_channel not in (None, getattr(destination, "id", None))
        trigger = None
        if not dm and not elsewhere:
            trigger = await _origin(destination, delivery.trigger)
        origin = trigger
        if origin is None and not dm:
            origin = await _origin(destination, delivery.reply_to)
        body = _MENTION.sub("", delivery.text).strip()
        if delivery.quote and trigger is None:
            body = f"{body}\n> {delivery.quote}"
        if delivery.mention and not dm and (origin is None or trigger is not None):
            body = f"<@{objective.owner_id}> {body}".strip()
        linked = (dm or elsewhere) and delivery.footer_linked
        footer_text = delivery.footer_linked if linked else delivery.footer
        footer = f"-# {footer_text}" if footer_text else ""
        mentions = discord.AllowedMentions(
            users=[discord.Object(id=objective.owner_id)],
            roles=False,
            everyone=False,
            replied_user=delivery.mention and trigger is None,
        )
        sent = await _post(destination, body, footer, delivery, origin, mentions)
        app = getattr(self._bot, "app", None)
        if isinstance(app, App) and sent is not None and not dm:
            app.conversation.note_posted(sent.channel.id, delivery.text, message_id=sent.id)

    async def notify(self, objective: Objective, text: str) -> None:
        user = self._bot.get_user(objective.owner_id) or await self._bot.fetch_user(
            objective.owner_id
        )
        try:
            await user.send(
                quiet_links(text[:1900]), allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException:
            logger.warning("Message privé refusé par %s", objective.owner_id)

    async def _destination(self, objective: Objective) -> discord.abc.Messageable:
        if objective.deliver == "channel" and objective.channel_ids:
            found = self._bot.get_channel(objective.channel_ids[0])
            if found is None:
                try:
                    found = await self._bot.fetch_channel(objective.channel_ids[0])
                except discord.HTTPException:
                    found = None
            if isinstance(found, discord.abc.Messageable):
                return found
        return self._bot.get_user(objective.owner_id) or await self._bot.fetch_user(
            objective.owner_id
        )


async def _origin(
    destination: discord.abc.Messageable, message_id: int | None
) -> discord.Message | None:
    if message_id is None or not hasattr(destination, "fetch_message"):
        return None
    try:
        return await destination.fetch_message(message_id)
    except discord.HTTPException:
        return None


async def _post(
    destination: discord.abc.Messageable,
    body: str,
    footer: str,
    delivery: Delivery,
    origin: discord.Message | None,
    mentions: discord.AllowedMentions,
) -> discord.Message | None:
    if delivery.cards:
        views = build_views(intro=body, cards=delivery.cards, outro=footer)
        first: discord.Message | None = None
        for index, view in enumerate(views):
            if index == 0 and origin is not None:
                sent = await origin.reply(view=view, allowed_mentions=mentions)
            else:
                sent = await destination.send(view=view, allowed_mentions=mentions)
            first = first or sent
        return first
    chunks = list(split_message(quiet_links(f"{body}\n{footer}".strip())))
    first = None
    for index, chunk in enumerate(chunks):
        if index == 0 and origin is not None:
            sent = await origin.reply(chunk, allowed_mentions=mentions)
        else:
            sent = await destination.send(chunk, allowed_mentions=mentions)
        first = first or sent
    return first
