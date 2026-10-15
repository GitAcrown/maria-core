"""Pose les réactions de MARIA, apprend celles du serveur, et peut rejoindre une réaction."""

import asyncio
import logging
import re
from datetime import UTC, datetime

import discord
from discord.ext import commands

from maria_core.app import App
from maria_core.conversation.model import ReplyMode
from maria_core.objectives.signals import ObjectiveSignal
from maria_core.social.service import ReactionSeen
from maria_core.ui.emojis import FALLBACKS, TRANSCRIPT

logger = logging.getLogger(__name__)

_CUSTOM = re.compile(r"<a?:\w+:(\d+)>")
# Les emojis d'interface (et 📝, déclencheur de transcription) ne s'apprennent pas.
_IGNORED = frozenset(FALLBACKS) | {FALLBACKS[TRANSCRIPT]}


class ReactionCog(commands.Cog):
    def __init__(self, bot: commands.Bot, app: App) -> None:
        self.bot = bot
        self.app = app

    async def add(self, channel_id: int, message_id: int, emoji: str) -> bool:
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel | discord.Thread | discord.VoiceChannel):
            return False
        try:
            await channel.get_partial_message(message_id).add_reaction(emoji)
        except discord.HTTPException as exc:
            logger.warning("Réaction %s refusée dans %s : %s", emoji, channel_id, exc.status)
            return False
        return True

    def usable(self, emoji: str) -> bool:
        """Un emoji custom n'est posable que si MARIA le voit (serveur commun)."""
        if emoji in _IGNORED:
            return False
        match = _CUSTOM.fullmatch(emoji)
        if match is None:
            return True
        found = self.bot.get_emoji(int(match.group(1)))
        return found is not None and found.is_usable()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        user = self.bot.user
        if user is None or payload.user_id == user.id or payload.guild_id is None:
            return
        if payload.member is not None and payload.member.bot:
            return
        emoji = str(payload.emoji)
        self._publish(payload, emoji)
        if not self.usable(emoji):
            return
        author_id, author_is_bot, age, excerpt = await self._facts(payload)
        enabled = await asyncio.to_thread(self._enabled, payload.guild_id)
        await self.app.social.notice_reaction(
            ReactionSeen(
                guild_id=payload.guild_id,
                channel_id=payload.channel_id,
                message_id=payload.message_id,
                user_id=payload.user_id,
                emoji=emoji,
                author_id=author_id,
                author_is_bot=author_is_bot or author_id == user.id,
                age_s=age,
                excerpt=excerpt,
                enabled=enabled,
            )
        )

    def _publish(self, payload: discord.RawReactionActionEvent, emoji: str) -> None:
        """Une réaction posée par quelqu'un : les écoutes d'emoji la voient."""
        channel = self.bot.get_channel(payload.channel_id)
        place = getattr(channel, "parent_id", None) or payload.channel_id
        member = payload.member
        self.app.events.publish_soon(
            ObjectiveSignal(
                kind="reaction",
                key=f"reaction:{payload.message_id}:{payload.user_id}:{emoji}",
                channel_id=int(place),
                guild_id=payload.guild_id,
                user_id=payload.user_id,
                author_name=member.display_name if member is not None else "",
                url=f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}",
                message_id=payload.message_id,
                emoji=emoji,
                emoji_name=payload.emoji.name or "",
            )
        )

    async def _facts(
        self, payload: discord.RawReactionActionEvent
    ) -> tuple[int | None, bool, float, str]:
        """Auteur, bot ou non, âge et extrait du message, sans appel API si on l'a déjà vu."""
        seen = self.app.social.room.message(payload.message_id)
        if seen is not None:
            age = self.app.social.room.now() - seen.at
            return seen.author_id, seen.from_bot, age, seen.text
        channel = self.bot.get_channel(payload.channel_id)
        if channel is None or not hasattr(channel, "fetch_message"):
            return payload.message_author_id, False, 0.0, ""
        try:
            message = await channel.fetch_message(payload.message_id)  # type: ignore[union-attr]
        except discord.HTTPException:
            return payload.message_author_id, False, 0.0, ""
        return message.author.id, message.author.bot, _age(message), message.clean_content[:300]

    def _enabled(self, guild_id: int) -> bool:
        row = self.app.database.fetchone(
            "SELECT mode FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )
        return row is None or str(row["mode"]) != ReplyMode.OFF.value


def _age(message: discord.Message | None) -> float:
    if message is None:
        return 0.0
    return max(0.0, (datetime.now(UTC) - message.created_at).total_seconds())
