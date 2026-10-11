"""Apprend les emojis du serveur et peut rejoindre une réaction déjà là."""

import logging

import discord
from discord.ext import commands

from maria_core.app import App

logger = logging.getLogger(__name__)


class ReactionCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def add(self, channel_id: int, message_id: int, emoji: str) -> None:
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel | discord.Thread | discord.VoiceChannel):
            return
        try:
            await channel.get_partial_message(message_id).add_reaction(emoji)
        except discord.HTTPException as exc:
            logger.warning("Réaction %s refusée dans %s : %s", emoji, channel_id, exc.status)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        user = self.bot.user
        if user is None or payload.user_id == user.id or payload.guild_id is None:
            return
        if payload.emoji.id is not None and self.bot.get_emoji(payload.emoji.id) is None:
            return
        app = getattr(self.bot, "app", None)
        if not isinstance(app, App):
            return
        await app.social.notice_reaction(
            guild_id=payload.guild_id,
            channel_id=payload.channel_id,
            message_id=payload.message_id,
            user_id=payload.user_id,
            emoji=str(payload.emoji),
        )
