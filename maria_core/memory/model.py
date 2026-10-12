"""Souvenir, proposition, révision."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Memory:
    id: int
    scope: str
    subject_id: int
    guild_id: int | None
    content: str
    source: str
    created_by: int
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None
    deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class Proposal:
    id: int
    guild_id: int | None
    channel_id: int | None
    subject_user_id: int | None
    scope: str
    content: str
    status: str
    created_at: datetime
    reply_message_id: int | None
    review_of: int | None = None


@dataclass(frozen=True, slots=True)
class MemoryAsk:
    proposal_id: int
    text: str
