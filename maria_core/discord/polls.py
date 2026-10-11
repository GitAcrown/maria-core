"""Poste un sondage natif et le note dans la base."""

import asyncio
from datetime import timedelta

import discord
from discord.ext import commands

from maria_core.capabilities.builtin.polls import PollStore


class DiscordPolls:
    def __init__(self, bot: commands.Bot, store: PollStore) -> None:
        self._bot = bot
        self._store = store

    async def post(
        self,
        *,
        channel_id: int,
        guild_id: int,
        author_id: int,
        question: str,
        options: tuple[str, ...],
        hours: int,
        multiple: bool,
    ) -> int:
        channel = self._bot.get_channel(channel_id) or await self._bot.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError("Ce salon ne reçoit pas de message.")
        poll = discord.Poll(question=question, duration=timedelta(hours=hours), multiple=multiple)
        for option in options:
            poll.add_answer(text=option)
        sent = await channel.send(poll=poll)
        await asyncio.to_thread(
            self._store.save,
            message_id=sent.id,
            channel_id=channel_id,
            guild_id=guild_id,
            author_id=author_id,
            question=question,
            options=options,
            hours=hours,
        )
        return sent.id
