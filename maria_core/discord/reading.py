"""Historique Discord récent, pour le résumé de salon."""

import discord
from discord.ext import commands


class DiscordHistory:
    def __init__(self, bot: commands.Bot) -> None:
        self._bot = bot

    async def recent(self, channel_id: int, limit: int) -> tuple[str, ...]:
        channel = await self._channel(channel_id)
        if channel is None or not hasattr(channel, "history"):
            return ()
        lines: list[str] = []
        async for message in channel.history(limit=limit):
            text = (message.content or "").strip()
            if text:
                lines.append(f"{message.author.display_name}: {text}")
        lines.reverse()
        return tuple(lines)

    async def _channel(self, channel_id: int) -> discord.abc.Messageable | None:
        found = self._bot.get_channel(channel_id)
        if found is None:
            try:
                found = await self._bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
        if isinstance(found, discord.abc.Messageable):
            return found
        return None
