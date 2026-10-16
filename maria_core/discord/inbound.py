"""Traduit un message Discord en message normalisé."""

import logging
import re

import discord
from discord.ext import commands

from maria_core.conversation.model import AudioRef, FileRef, ImageRef, Inbound, Quote

logger = logging.getLogger(__name__)

_AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".m4a", ".flac", ".webm", ".aac")
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
_VOICE_FLAG = 1 << 13
_MAX_AUDIO_BYTES = 25 * 1024 * 1024
_MAX_FILES = 8
_MAX_IMAGES = 4
_IMAGE_URL = re.compile(r"https?://\S+?\.(?:png|jpe?g|webp|gif)(?:\?\S*)?", re.IGNORECASE)


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
    quote = await quote_of(message, user.id)
    return Inbound(
        channel_id=message.channel.id,
        message_id=message.id,
        guild_id=message.guild.id if message.guild else None,
        author_id=message.author.id,
        author_name=message.author.name,
        text=message.content or "",
        is_dm=message.guild is None,
        author_is_bot=message.author.bot,
        mentioned=any(mention.id == user.id for mention in message.mentions),
        reply_to_bot=quote is not None and quote.from_bot_self,
        mention_everyone=message.mention_everyone,
        edited=edited,
        author_is_owner=await bot.is_owner(message.author),
        author_is_moderator=_is_moderator(message),
        bot_names=bot_names(bot, message.guild),
        images=_images(message),
        audio=_audio(message),
        mentioned_ids=tuple(item.id for item in message.mentions if item.id != user.id),
        mentioned_names=tuple(
            (item.id, item.name) for item in message.mentions if item.id != user.id
        ),
        created_at=message.created_at,
        settings_channel_id=_parent_id(message.channel),
        channel_label=channel_label(message.channel),
        quote=quote,
        extras=_extras(message),
        files=_files(message),
        has_media=bool(message.attachments or message.stickers or message.embeds),
    )


async def quote_of(message: discord.Message, bot_id: int) -> Quote | None:
    reference = message.reference
    if reference is None or reference.message_id is None:
        return None
    resolved = reference.resolved
    if not isinstance(resolved, discord.Message):
        try:
            resolved = await message.channel.fetch_message(reference.message_id)
        except discord.HTTPException:
            return None
    return Quote(
        message_id=resolved.id,
        author_id=resolved.author.id,
        author_name=resolved.author.name,
        text=_preview(resolved),
        from_bot_self=resolved.author.id == bot_id,
        from_bot=resolved.author.bot,
        images=_images(resolved),
    )


def bot_names(bot: commands.Bot, guild: discord.Guild | None) -> tuple[str, ...]:
    user = bot.user
    if user is None:
        return ()
    names = [user.name, user.display_name]
    if guild is not None:
        member = guild.me
        if member is not None and member.nick:
            names.append(member.nick)
    return tuple(dict.fromkeys(name for name in names if name))


def channel_label(channel: object) -> str:
    if isinstance(channel, discord.DMChannel):
        return "message privé"
    parts: list[str] = []
    target = channel.parent if isinstance(channel, discord.Thread) else channel
    if isinstance(channel, discord.Thread) and target is not None:
        parts.append(f"thread « {channel.name} » dans #{target.name}")
    elif hasattr(target, "name"):
        parts.append(f"#{getattr(target, 'name', '')}")
    if isinstance(target, discord.TextChannel):
        if target.category:
            parts.append(f"catégorie {target.category.name}")
        if target.topic:
            parts.append(f"sujet « {target.topic[:120]} »")
        if target.nsfw:
            parts.append("NSFW")
    guild = getattr(channel, "guild", None)
    if guild is not None:
        parts.append(f"serveur {guild.name} ({guild.member_count} membres)")
    return " · ".join(parts)


def image_url(url: str, filename: str = "") -> str:
    """Un GIF animé est refusé par le modèle : Discord en sert une image fixe."""
    if (filename or url.split("?", 1)[0]).lower().endswith(".gif"):
        return f"{url}{'&' if '?' in url else '?'}format=png"
    return url


def _parent_id(channel: object) -> int | None:
    if isinstance(channel, discord.Thread) and channel.parent_id:
        return channel.parent_id
    return None


def _is_command(message: discord.Message, bot: commands.Bot) -> bool:
    prefix = bot.command_prefix
    return isinstance(prefix, str) and message.content.startswith(prefix)


def _is_moderator(message: discord.Message) -> bool:
    author = message.author
    if not isinstance(author, discord.Member):
        return False
    return bool(author.guild_permissions.manage_messages)


def _images(message: discord.Message) -> tuple[ImageRef, ...]:
    return _all_images(message)[:_MAX_IMAGES]


def _all_images(message: discord.Message) -> tuple[ImageRef, ...]:
    refs = [
        ImageRef(url=image_url(item.url, item.filename or ""))
        for item in message.attachments
        if _is_image(item) and not _is_audio(item, message)
    ]
    refs.extend(
        ImageRef(url=image_url(match.group(0)))
        for match in _IMAGE_URL.finditer(message.content or "")
    )
    refs.extend(ImageRef(url=sticker.url) for sticker in message.stickers if sticker.url)
    for embed in message.embeds:
        for media in (embed.image, embed.thumbnail):
            if media and media.url:
                refs.append(ImageRef(url=image_url(media.url)))
    return tuple(dict.fromkeys(refs))


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
        seconds=getattr(attachment, "duration", None),
        voice=bool(message.flags.value & _VOICE_FLAG),
    )


def _files(message: discord.Message) -> tuple[FileRef, ...]:
    """Tout ce qui n'est ni image ni audio ; `attachments` décide ensuite de ce qui se lit."""
    return tuple(
        FileRef(
            filename=item.filename or "fichier",
            size=item.size,
            load=item.read,
            content_type=item.content_type or "",
        )
        for item in message.attachments
        if not _is_image(item) and not _is_audio(item, message)
    )[:_MAX_FILES]


def _extras(message: discord.Message) -> tuple[str, ...]:
    found: list[str] = []
    for embed in message.embeds:
        text = embed_text(embed)
        if text:
            found.append(f"[Embed] {text[:600]}")
    for snapshot in getattr(message, "message_snapshots", None) or []:
        content = " ".join((getattr(snapshot, "content", "") or "").split())
        if content:
            found.append(f"[Message transféré] « {content[:300]} »")
    for sticker in message.stickers:
        found.append(f"[Sticker {sticker.name}]")
    if message.components and not message.content:
        found.append("[Vue interactive]")
    dropped = len(_all_images(message)) - _MAX_IMAGES
    if dropped > 0:
        found.append(f"[{dropped} image(s) en plus, non vues : au-delà de {_MAX_IMAGES}]")
    return tuple(found[:6])


def embed_text(embed: discord.Embed) -> str:
    lines: list[str] = []
    if embed.author and embed.author.name:
        lines.append(f"[{embed.author.name}]")
    if embed.title:
        lines.append(f"{embed.title} ({embed.url})" if embed.url else embed.title)
    if embed.description:
        lines.append(embed.description[:500])
    lines.extend(f"{item.name}: {str(item.value)[:200]}" for item in embed.fields[:6] if item.name)
    if embed.footer and embed.footer.text:
        lines.append(f"({embed.footer.text[:120]})")
    return " | ".join(lines)


def _preview(message: discord.Message) -> str:
    text = " ".join((message.clean_content or message.content or "").split())
    if not text:
        text = next((embed_text(embed) for embed in message.embeds if embed_text(embed)), "")
    if not text and message.attachments:
        text = "[média]"
    if not text and message.stickers:
        text = "[sticker]"
    if not text and message.components:
        text = "[vue interactive]"
    return text[:400]


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
