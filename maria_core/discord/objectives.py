"""Envoie le texte d'un objectif dans le salon ou en message privé."""

import discord
from discord.ext import commands

from maria_core.objectives.model import Objective


class DiscordCourier:
    def __init__(self, bot: commands.Bot) -> None:
        self._bot = bot

    async def send(self, objective: Objective, text: str) -> None:
        destination = await self._channel(objective)
        await destination.send(text[:2000])

    async def notify(self, objective: Objective, text: str) -> None:
        user = self._bot.get_user(objective.owner_id) or await self._bot.fetch_user(
            objective.owner_id
        )
        await user.send(text[:2000])

    async def _channel(self, objective: Objective) -> discord.abc.Messageable:
        if objective.deliver == "channel" and objective.channel_ids:
            found = self._bot.get_channel(objective.channel_ids[0])
            if found is None:
                found = await self._bot.fetch_channel(objective.channel_ids[0])
            if isinstance(found, discord.abc.Messageable):
                return found
        user = self._bot.get_user(objective.owner_id) or await self._bot.fetch_user(
            objective.owner_id
        )
        return user
