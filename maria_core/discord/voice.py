"""Messages vocaux : transcription automatique, à la demande, ou quand on parle à MARIA.

La transcription est postée en citation : tout le salon la lit, pas seulement le modèle.
"""

import asyncio
import logging

import discord
from discord.ext import commands

from maria_core.app import App
from maria_core.conversation.model import Inbound
from maria_core.conversation.policy import load_policy
from maria_core.discord.inbound import inbound_from_message
from maria_core.ui.emojis import TRANSCRIPT, TRANSCRIPT_SUB

logger = logging.getLogger(__name__)

TRANSCRIBE_EMOJI = TRANSCRIPT
AUTO_MAX_SECONDS = 120
_QUOTE_CHARS = 1800


async def prepare_voice(app: App, message: discord.Message, inbound: Inbound) -> Inbound:
    """Transcrit si le salon le veut ou si on parle à MARIA ; sinon propose la réaction."""
    audio = inbound.audio
    if audio is None or inbound.author_is_bot or inbound.is_dm:
        return inbound
    policy = await asyncio.to_thread(load_policy, app.database, inbound)
    short = audio.seconds is None or audio.seconds <= AUTO_MAX_SECONDS
    automatic = policy.auto_transcribe and audio.voice and short
    addressed = inbound.mentioned or inbound.reply_to_bot
    if not (automatic or addressed):
        await _offer(message)
        return inbound
    transcript = await post_transcript(app, message, inbound, detail="")
    if not transcript:
        return inbound
    return inbound.with_text(f"{inbound.text}\n{transcript}".strip(), transcribed=True)


async def post_transcript(
    app: App, message: discord.Message, inbound: Inbound, *, detail: str
) -> str:
    if inbound.audio is None:
        return ""
    async with message.channel.typing():
        transcript = await app.conversation.transcribe(inbound.audio)
    if not transcript:
        await _say(message, "-# Transcription impossible.")
        return ""
    clipped = transcript if len(transcript) <= _QUOTE_CHARS else transcript[:_QUOTE_CHARS] + "…"
    quoted = "\n".join(f"> {line}" if line else ">" for line in clipped.splitlines())
    suffix = f"\n-# {TRANSCRIPT_LABEL}" + (f" · {detail}" if detail else "")
    await _say(message, f"{quoted}{suffix}")
    return transcript


TRANSCRIPT_LABEL = f"{TRANSCRIPT_SUB} **Transcription**"


class VoiceCog(commands.Cog):
    """Transcription à la demande : la réaction de transcription sur un message audio."""

    def __init__(self, bot: commands.Bot, app: App) -> None:
        self.bot = bot
        self.app = app

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        user = self.bot.user
        if user is None or payload.user_id == user.id or str(payload.emoji) != TRANSCRIBE_EMOJI:
            return
        if payload.member is not None and payload.member.bot:
            return
        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, discord.abc.Messageable) or not hasattr(
            channel, "fetch_message"
        ):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return
        inbound = await inbound_from_message(message, bot=self.bot, edited=False)
        if inbound is None or inbound.audio is None:
            return
        await _drop_reaction(message, payload)
        requester = payload.member.display_name if payload.member else ""
        transcript = await post_transcript(self.app, message, inbound, detail=requester)
        if transcript:
            self.app.conversation.attach_transcript(inbound, transcript)


async def _offer(message: discord.Message) -> None:
    try:
        await message.add_reaction(TRANSCRIBE_EMOJI)
    except discord.HTTPException:
        logger.debug("Réaction de transcription refusée", exc_info=True)


async def _drop_reaction(message: discord.Message, payload: discord.RawReactionActionEvent) -> None:
    try:
        await message.remove_reaction(payload.emoji, discord.Object(id=payload.user_id))
    except discord.HTTPException:
        logger.debug("Réaction impossible à retirer", exc_info=True)


async def _say(message: discord.Message, text: str) -> None:
    try:
        await message.reply(
            text, mention_author=False, allowed_mentions=discord.AllowedMentions.none()
        )
    except discord.HTTPException:
        logger.warning("Transcription non postée dans %s", message.channel.id)
