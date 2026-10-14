"""Règles de salon lues dans la base. Absentes : mode strict, pas de transcription auto."""

import sqlite3

from maria_core.conversation.model import Inbound, Policy, ReplyMode
from maria_core.db import Database


def load_policy(database: Database, message: Inbound) -> Policy:
    if message.guild_id is None:
        return Policy(mode=ReplyMode.STRICT)
    guild = database.fetchone(
        "SELECT mode, reply_limit FROM guild_settings WHERE guild_id = ?",
        (message.guild_id,),
    )
    channel = database.fetchone(
        """
        SELECT respond_everyone, auto_transcribe
        FROM channel_settings WHERE channel_id = ?
        """,
        (message.policy_channel_id,),
    )
    return Policy(
        mode=_mode(guild),
        respond_everyone=_flag(channel, "respond_everyone"),
        auto_transcribe=_flag(channel, "auto_transcribe"),
        limit=_limit(guild),
    )


def save_mode(database: Database, guild_id: int, mode: str, now: str) -> str:
    chosen = ReplyMode(mode)
    database.execute(
        """
        INSERT INTO guild_settings (guild_id, mode, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            mode = excluded.mode,
            updated_at = excluded.updated_at
        """,
        (guild_id, chosen.value, now),
    )
    return chosen.value


LIMITS = ("none", "normal", "strict")


def save_limit(database: Database, guild_id: int, limit: str, now: str) -> None:
    if limit not in LIMITS:
        raise ValueError(f"Limite inconnue : {limit}.")
    database.execute(
        """
        INSERT INTO guild_settings (guild_id, reply_limit, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            reply_limit = excluded.reply_limit,
            updated_at = excluded.updated_at
        """,
        (guild_id, limit, now),
    )


def _limit(row: sqlite3.Row | None) -> str:
    value = "none" if row is None else str(row["reply_limit"] or "none")
    return value if value in LIMITS else "none"


def save_everyone(database: Database, channel_id: int, guild_id: int, enabled: bool) -> None:
    _save_flag(database, channel_id, guild_id, "respond_everyone", enabled)


def save_transcribe(database: Database, channel_id: int, guild_id: int, enabled: bool) -> None:
    _save_flag(database, channel_id, guild_id, "auto_transcribe", enabled)


def _save_flag(
    database: Database,
    channel_id: int,
    guild_id: int,
    column: str,
    enabled: bool,
) -> None:
    if column not in {"respond_everyone", "auto_transcribe"}:
        raise ValueError(column)
    database.execute(
        f"""
        INSERT INTO channel_settings (channel_id, guild_id, {column})
        VALUES (?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET {column} = excluded.{column}
        """,
        (channel_id, guild_id, int(enabled)),
    )


def _mode(row: sqlite3.Row | None) -> ReplyMode:
    if row is None:
        return ReplyMode.STRICT
    try:
        return ReplyMode(str(row["mode"]))
    except ValueError:
        return ReplyMode.STRICT


def _flag(row: sqlite3.Row | None, column: str) -> bool:
    if row is None:
        return False
    return bool(row[column])
