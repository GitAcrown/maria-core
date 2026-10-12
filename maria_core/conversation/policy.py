"""Règles de salon lues dans la base. Absentes : mode strict, pas de transcription auto."""

import sqlite3

from maria_core.conversation.model import Inbound, Policy, ReplyMode
from maria_core.db import Database


def load_policy(database: Database, message: Inbound) -> Policy:
    if message.guild_id is None:
        return Policy(mode=ReplyMode.STRICT)
    guild = database.fetchone(
        "SELECT mode, personality FROM guild_settings WHERE guild_id = ?",
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
        personality=_text(guild, "personality"),
        respond_everyone=_flag(channel, "respond_everyone"),
        auto_transcribe=_flag(channel, "auto_transcribe"),
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


def save_personality(database: Database, guild_id: int, text: str, now: str) -> None:
    database.execute(
        """
        INSERT INTO guild_settings (guild_id, personality, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            personality = excluded.personality,
            updated_at = excluded.updated_at
        """,
        (guild_id, text, now),
    )


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


def _text(row: sqlite3.Row | None, column: str) -> str:
    if row is None:
        return ""
    return str(row[column] or "")


def _flag(row: sqlite3.Row | None, column: str) -> bool:
    if row is None:
        return False
    return bool(row[column])
