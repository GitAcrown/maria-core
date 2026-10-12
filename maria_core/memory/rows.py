"""Lignes SQLite -> objets mémoire."""

import sqlite3
from datetime import UTC, datetime

from maria_core.memory.model import Memory, Proposal
from maria_core.memory.policy import Actor


def accepted_subject(proposal: Proposal, actor: Actor) -> int:
    if proposal.scope == "guild":
        return proposal.guild_id or 0
    if proposal.scope == "self":
        return 0
    return proposal.subject_user_id or actor.user_id


def visible(memory: Memory, user_id: int, guild_id: int | None, mentioned: tuple[int, ...]) -> bool:
    if memory.scope == "self":
        return True
    if memory.scope == "guild":
        return guild_id is not None and memory.guild_id == guild_id
    allowed = {user_id, *mentioned}
    return memory.scope == "user" and memory.subject_id in allowed


def memory_row(row: sqlite3.Row) -> Memory:
    return Memory(
        id=int(row["id"]),
        scope=str(row["scope"]),
        subject_id=int(row["subject_id"]),
        guild_id=int(row["guild_id"]) if row["guild_id"] is not None else None,
        content=str(row["content"]),
        source=str(row["source"]),
        created_by=int(row["created_by"]),
        created_at=required_time(row["created_at"]),
        updated_at=required_time(row["updated_at"]),
        last_used_at=parse_time(row["last_used_at"]),
        deleted_at=parse_time(row["deleted_at"]),
    )


def proposal_row(row: sqlite3.Row) -> Proposal:
    return Proposal(
        id=int(row["id"]),
        guild_id=int(row["guild_id"]) if row["guild_id"] is not None else None,
        channel_id=int(row["channel_id"]) if row["channel_id"] is not None else None,
        subject_user_id=int(row["subject_user_id"]) if row["subject_user_id"] is not None else None,
        scope=str(row["scope"]),
        content=str(row["content"]),
        status=str(row["status"]),
        created_at=required_time(row["created_at"]),
        reply_message_id=int(row["reply_message_id"])
        if row["reply_message_id"] is not None
        else None,
        review_of=review_of(row),
    )


def review_of(row: sqlite3.Row) -> int | None:
    """Une révision est une proposition sans message source qui pointe un souvenir."""
    if row["source_message_id"] is not None or row["memory_id"] is None:
        return None
    if str(row["status"]) != "open":
        return None
    return int(row["memory_id"])


def required_time(raw: object) -> datetime:
    parsed = parse_time(raw)
    if parsed is None:
        raise ValueError("Date de souvenir manquante.")
    return parsed


def parse_time(raw: object) -> datetime | None:
    if not raw:
        return None
    moment = datetime.fromisoformat(str(raw))
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment
