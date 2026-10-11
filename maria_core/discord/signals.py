"""Publie les arrivées vocales et les nouveaux membres vers les objectifs."""

import time

import discord
from discord.ext import commands

from maria_core.app import App
from maria_core.objectives.signals import ObjectiveSignal


class SignalCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot or before.channel is not None or after.channel is None:
            return
        await _publish(
            self.bot,
            ObjectiveSignal(
                kind="voice",
                key=f"voice:{member.id}:{after.channel.id}:{int(time.time())}",
                channel_id=after.channel.id,
                guild_id=member.guild.id,
                user_id=member.id,
            ),
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        await _publish(
            self.bot,
            ObjectiveSignal(
                kind="join",
                key=f"join:{member.id}",
                channel_id=0,
                guild_id=member.guild.id,
                user_id=member.id,
            ),
        )


async def _publish(bot: commands.Bot, signal: ObjectiveSignal) -> None:
    app = getattr(bot, "app", None)
    if isinstance(app, App):
        app.events.publish_soon(signal)
