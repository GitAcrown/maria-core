"""Historique Discord d'un salon, pour le résumé. Seulement ce que la personne peut lire."""

from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from maria_core.capabilities.ports import HistoryWindow
from maria_core.discord.inbound import embed_text

_PARIS = ZoneInfo("Europe/Paris")
_HARD_CAP = 4000


class DiscordHistory:
    def __init__(self, bot: commands.Bot) -> None:
        self._bot = bot

    async def history(
        self,
        channel_id: int,
        window: HistoryWindow,
        *,
        user_id: int,
        guild_id: int | None,
    ) -> tuple[str, ...] | str:
        channel = await self._channel(channel_id)
        if channel is None:
            return "Salon introuvable."
        refused = _refused(channel, user_id, guild_id)
        if refused:
            return refused
        limit = _HARD_CAP if window.after is not None else window.limit
        lines: list[str] = []
        try:
            async for message in channel.history(
                limit=limit, after=window.after, oldest_first=False
            ):
                line = _line(message)
                if line:
                    lines.append(line)
        except discord.Forbidden:
            return "Je n'ai pas le droit de lire l'historique de ce salon."
        except discord.HTTPException as exc:
            return f"Lecture de l'historique impossible : {exc.status}"
        lines.reverse()
        return tuple(lines)

    async def _channel(self, channel_id: int) -> discord.abc.Messageable | None:
        found = self._bot.get_channel(channel_id)
        if found is None:
            try:
                found = await self._bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
        if isinstance(found, discord.TextChannel | discord.Thread | discord.VoiceChannel):
            return found
        return None


def _refused(channel: object, user_id: int, guild_id: int | None) -> str:
    guild = getattr(channel, "guild", None)
    if guild is None or guild.id != guild_id:
        return "Je ne lis que les salons de ce serveur."
    member = guild.get_member(user_id)
    if member is None:
        return "Membre introuvable."
    permissions = channel.permissions_for(member)  # type: ignore[attr-defined]
    if not (permissions.read_messages and permissions.read_message_history):
        return "Tu n'as pas accès à ce salon."
    return ""


def _line(message: discord.Message) -> str:
    text = " ".join((message.clean_content or "").split())
    if not text:
        text = next((embed_text(item) for item in message.embeds if embed_text(item)), "")
    if not text and message.attachments:
        text = "[média]"
    if not text:
        return ""
    stamp = message.created_at.astimezone(_PARIS).strftime("%H:%M")
    return f"[{stamp}] {message.author.display_name} : {text[:600]}"
