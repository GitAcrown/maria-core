"""Publie les mouvements vocaux et les nouveaux membres vers les objectifs."""

import time

import discord
from discord.ext import commands

from maria_core.app import App
from maria_core.objectives.signals import ObjectiveSignal


def voice_transitions(
    before_id: int, after_id: int, before_stream: bool, after_stream: bool
) -> list[tuple[str, int]]:
    """Rejoindre (y compris changer de salon), quitter pour de bon, lancer un stream.

    Un mute ou une caméra ne compte pas. Repris de MARIA_R.
    """
    found: list[tuple[str, int]] = []
    if before_id != after_id:
        if after_id:
            found.append(("voice_join", after_id))
        if before_id and not after_id:
            found.append(("voice_leave", before_id))
    if after_id and not before_stream and after_stream:
        found.append(("voice_stream", after_id))
    return found


class SignalCog(commands.Cog):
    def __init__(self, bot: commands.Bot, app: App) -> None:
        self.bot = bot
        self.app = app

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return
        events = voice_transitions(
            before.channel.id if before.channel else 0,
            after.channel.id if after.channel else 0,
            bool(before.self_stream),
            bool(after.self_stream),
        )
        stamp = int(time.time())
        for kind, channel_id in events:
            place = before.channel if kind == "voice_leave" else after.channel
            self.app.events.publish_soon(
                ObjectiveSignal(
                    kind=kind,
                    key=f"{kind}:{member.id}:{channel_id}:{stamp}",
                    channel_id=channel_id,
                    guild_id=member.guild.id,
                    user_id=member.id,
                    author_name=member.display_name,
                    place=getattr(place, "name", "") or "",
                )
            )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        self.app.events.publish_soon(
            ObjectiveSignal(
                kind="join",
                key=f"join:{member.guild.id}:{member.id}:{int(time.time())}",
                channel_id=0,
                guild_id=member.guild.id,
                user_id=member.id,
                author_name=member.display_name,
                place=member.guild.name,
            )
        )
