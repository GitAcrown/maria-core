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
        (message.channel_id,),
    )
    return Policy(
        mode=_mode(guild),
        personality=_text(guild, "personality"),
        respond_everyone=_flag(channel, "respond_everyone"),
        auto_transcribe=_flag(channel, "auto_transcribe"),
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
