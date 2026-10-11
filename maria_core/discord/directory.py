"""Répertoire Discord pour les capacités, sans règle métier."""

import discord
from discord.ext import commands

from maria_core.capabilities.ports import ChannelCard, MemberCard


class DiscordDirectory:
    def __init__(self, bot: commands.Bot) -> None:
        self._bot = bot

    async def members(self, guild_id: int, search: str) -> tuple[MemberCard, ...]:
        guild = self._bot.get_guild(guild_id)
        if guild is None:
            return ()
        query = search.casefold().strip()
        found: list[MemberCard] = []
        for member in guild.members:
            if query and not _matches(member, query):
                continue
            found.append(_card(member))
            if len(found) >= 20:
                break
        return tuple(found)

    async def member(
        self,
        guild_id: int,
        user_id: int | None,
        username: str,
    ) -> MemberCard | None:
        guild = self._bot.get_guild(guild_id)
        if guild is None:
            return None
        member = await _find_member(guild, user_id, username)
        if member is None:
            return None
        return _card(member)

    async def channel(self, channel_id: int) -> ChannelCard | None:
        found = self._bot.get_channel(channel_id)
        if found is None:
            try:
                found = await self._bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
        return ChannelCard(
            channel_id=channel_id,
            name=str(getattr(found, "name", None) or channel_id),
            topic=str(getattr(found, "topic", None) or ""),
            kind=str(getattr(found, "type", "")),
        )


async def _find_member(
    guild: discord.Guild,
    user_id: int | None,
    username: str,
) -> discord.Member | None:
    if user_id is not None:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.HTTPException:
            return None
    if not username:
        return None
    return discord.utils.find(
        lambda item: item.name == username or item.display_name == username,
        guild.members,
    )


def _card(member: discord.Member) -> MemberCard:
    roles = tuple(role.name for role in member.roles if role.name != "@everyone")
    joined = member.joined_at.isoformat() if member.joined_at else ""
    return MemberCard(
        user_id=member.id, name=member.display_name, roles=roles[:12], joined_at=joined
    )


def _matches(member: discord.Member, query: str) -> bool:
    return query in member.display_name.casefold() or query in member.name.casefold()
