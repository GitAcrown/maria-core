"""Ce que l'adaptateur Discord fournit aux capacités, sans que celles-ci l'importent."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MemberCard:
    user_id: int
    name: str
    roles: tuple[str, ...]
    joined_at: str


@dataclass(frozen=True, slots=True)
class ChannelCard:
    channel_id: int
    name: str
    topic: str
    kind: str


class GuildDirectory(Protocol):
    async def members(self, guild_id: int, search: str) -> tuple[MemberCard, ...]: ...

    async def member(
        self,
        guild_id: int,
        user_id: int | None,
        username: str,
    ) -> MemberCard | None: ...

    async def channel(self, channel_id: int) -> ChannelCard | None: ...


class ChannelReader(Protocol):
    async def recent(self, channel_id: int, limit: int) -> tuple[str, ...]: ...


class PollPoster(Protocol):
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
    ) -> int: ...
