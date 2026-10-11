"""Traduit un message Discord en message normalisé."""

import logging

import discord
from discord.ext import commands

from maria_core.conversation.model import AudioRef, ImageRef, Inbound

logger = logging.getLogger(__name__)

_AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".m4a", ".flac", ".webm")
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
_VOICE_FLAG = 1 << 13
_MAX_AUDIO_BYTES = 25 * 1024 * 1024


async def inbound_from_message(
    message: discord.Message,
    *,
    bot: commands.Bot,
    edited: bool,
) -> Inbound | None:
    user = bot.user
    if user is None or message.author.id == user.id:
        return None
    if _is_command(message, bot):
        return None
    author_is_owner = await bot.is_owner(message.author)
    return Inbound(
        channel_id=message.channel.id,
        message_id=message.id,
        guild_id=message.guild.id if message.guild else None,
        author_id=message.author.id,
        author_name=message.author.display_name,
        text=message.content or "",
        is_dm=message.guild is None,
        author_is_bot=message.author.bot,
        mentioned=any(mention.id == user.id for mention in message.mentions),
        reply_to_bot=await _replies_to_bot(message, user.id),
        mention_everyone=message.mention_everyone,
        edited=edited,
        author_is_owner=author_is_owner,
        author_is_moderator=_is_moderator(message),
        bot_names=_bot_names(bot, message.guild),
        images=_images(message),
        audio=_audio(message),
        mentioned_ids=_mentioned_ids(message, user.id),
    )


def _mentioned_ids(message: discord.Message, bot_id: int) -> tuple[int, ...]:
    return tuple(user.id for user in message.mentions if user.id != bot_id)


def _is_command(message: discord.Message, bot: commands.Bot) -> bool:
    prefix = bot.command_prefix
    return isinstance(prefix, str) and message.content.startswith(prefix)


def _is_moderator(message: discord.Message) -> bool:
    author = message.author
    if not isinstance(author, discord.Member):
        return False
    return bool(author.guild_permissions.manage_messages)


def _bot_names(bot: commands.Bot, guild: discord.Guild | None) -> tuple[str, ...]:
    user = bot.user
    if user is None:
        return ()
    names = [user.name, user.display_name]
    if guild is not None:
        member = guild.me
        if member is not None and member.nick:
            names.append(member.nick)
    return tuple(dict.fromkeys(name for name in names if name))


def _images(message: discord.Message) -> tuple[ImageRef, ...]:
    refs = [
        ImageRef(url=attachment.url)
        for attachment in message.attachments
        if _is_image(attachment) and not _is_audio(attachment, message)
    ]
    return tuple(refs)


def _audio(message: discord.Message) -> AudioRef | None:
    attachment = next(
        (item for item in message.attachments if _is_audio(item, message)),
        None,
    )
    if attachment is None:
        return None
    if attachment.size > _MAX_AUDIO_BYTES:
        logger.info("Audio trop lourd ignoré pour le message %s", message.id)
        return None
    return AudioRef(
        filename=attachment.filename or "audio.ogg",
        size=attachment.size,
        load=attachment.read,
    )


async def _replies_to_bot(message: discord.Message, bot_id: int) -> bool:
    reference = message.reference
    if reference is None or reference.message_id is None:
        return False
    resolved = reference.resolved
    if not isinstance(resolved, discord.Message):
        try:
            resolved = await message.channel.fetch_message(reference.message_id)
        except discord.HTTPException:
            return False
    return isinstance(resolved, discord.Message) and resolved.author.id == bot_id


def _is_image(attachment: discord.Attachment) -> bool:
    content_type = attachment.content_type or ""
    name = (attachment.filename or "").lower()
    return content_type.startswith("image/") or name.endswith(_IMAGE_EXTENSIONS)


def _is_audio(attachment: discord.Attachment, message: discord.Message) -> bool:
    if message.flags.value & _VOICE_FLAG:
        return True
    content_type = attachment.content_type or ""
    name = (attachment.filename or "").lower()
    return content_type.startswith("audio/") or name.endswith(_AUDIO_EXTENSIONS)
