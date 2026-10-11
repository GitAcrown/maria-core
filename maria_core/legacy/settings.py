"""Réglages de salon, emojis appris, sondages encore stockés."""

import json
import re
import sqlite3
from datetime import UTC, datetime

from maria_core.legacy.model import ChannelDraft, EmojiDraft, GuildDraft, PollDraft, Skip
from maria_core.legacy.read import cell, moment, positive

_MODES = frozenset({"off", "strict", "greedy"})
_EMOJI_NAME = re.compile(r"^[A-Za-z0-9_]{2,32}$")
_KNOWN_GUILD_KEYS = frozenset({"chatbot_mode"})


def guild_draft(guild_id: int, rows: list[sqlite3.Row]) -> GuildDraft | Skip:
    pairs = _pairs(rows)
    mode = pairs.get("chatbot_mode", "strict")
    if mode not in _MODES:
        return Skip("serveur", str(guild_id), f"mode inconnu ({mode})")
    unknown = sorted(set(pairs) - _KNOWN_GUILD_KEYS)
    notice = f"clés ignorées : {', '.join(unknown)}" if unknown else ""
    return GuildDraft(guild_id=guild_id, mode=mode, notice=notice)


def channel_draft(
    channel_id: int,
    rows: list[sqlite3.Row],
    guild_id: int | None,
) -> ChannelDraft | Skip:
    if guild_id is None:
        return Skip("salon", str(channel_id), "serveur introuvable")
    pairs = _pairs(rows)
    everyone = _flag(pairs.get("respond_everyone"))
    transcribe = _flag(pairs.get("auto_transcribe"))
    if everyone is None or transcribe is None:
        return Skip("salon", str(channel_id), "réglage illisible")
    return ChannelDraft(channel_id, guild_id, everyone, transcribe)


def emoji_draft(row: sqlite3.Row, *, now: datetime) -> EmojiDraft | Skip:
    guild = positive(cell(row, "guild_id", 0))
    emoji = _emoji(row)
    if guild is None or not emoji:
        return Skip("emoji", str(cell(row, "emoji_id", "?")), "emoji illisible")
    uses = _uses(row)
    return EmojiDraft(guild, emoji, uses, _seen(row, now))


def poll_draft(row: sqlite3.Row) -> PollDraft | Skip:
    options = _options(cell(row, "options", ""))
    created = moment(cell(row, "created_at", ""))
    expires = moment(cell(row, "expires_at", ""))
    message = positive(cell(row, "message_id", 0))
    channel = positive(cell(row, "channel_id", 0))
    guild = positive(cell(row, "guild_id", 0))
    author = positive(cell(row, "author_id", 0))
    question = str(cell(row, "question", "")).strip()
    if (
        options is None
        or created is None
        or expires is None
        or message is None
        or channel is None
        or guild is None
        or author is None
        or not question
    ):
        return Skip("sondage", str(cell(row, "message_id", "?")), "sondage illisible")
    return PollDraft(
        message,
        channel,
        guild,
        author,
        question,
        tuple(options),
        created.isoformat(),
        expires.isoformat(),
    )


def channel_guilds(rows: list[sqlite3.Row] | None) -> dict[int, set[int]]:
    found: dict[int, set[int]] = {}
    for row in rows or []:
        guild = positive(cell(row, "guild_id", 0))
        if guild is None:
            continue
        for channel in _channel_ids(row):
            found.setdefault(channel, set()).add(guild)
    return found


def _pairs(rows: list[sqlite3.Row]) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for row in rows:
        try:
            key = row["key"]
            value = row["value"]
        except IndexError:
            continue
        pairs[str(key)] = "" if value is None else str(value)
    return pairs


def _flag(raw: str | None) -> int | None:
    if raw is None:
        return 0
    if raw in {"0", "1"}:
        return int(raw)
    return None


def _emoji(row: sqlite3.Row) -> str:
    try:
        emoji_id = int(str(cell(row, "emoji_id", 0)))
    except ValueError:
        return ""
    name = str(cell(row, "emoji_name", "")).strip()
    if emoji_id < 0:
        return name
    if not _EMOJI_NAME.fullmatch(name) or emoji_id <= 0:
        return ""
    prefix = "a" if int(str(cell(row, "animated", 0) or 0)) else ""
    return f"<{prefix}:{name}:{emoji_id}>"


def _uses(row: sqlite3.Row) -> int:
    try:
        return max(0, int(str(cell(row, "count", 0) or 0)))
    except ValueError:
        return 0


def _seen(row: sqlite3.Row, now: datetime) -> str:
    try:
        stamp = float(str(cell(row, "last_seen", "")))
    except ValueError:
        return now.isoformat()
    return datetime.fromtimestamp(stamp, UTC).isoformat()


def _options(raw: object) -> list[str] | None:
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or not data:
        return None
    if not all(isinstance(item, str) and item.strip() for item in data):
        return None
    return [item.strip() for item in data]


def _channel_ids(row: sqlite3.Row) -> tuple[int, ...]:
    found: list[int] = []
    direct = positive(cell(row, "channel_id", 0))
    if direct is not None:
        found.append(direct)
    raw = cell(row, "channel_ids", "")
    if not isinstance(raw, str) or not raw.strip():
        return tuple(found)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return tuple(found)
    if isinstance(data, list):
        for item in data:
            number = positive(item)
            if number is not None and number not in found:
                found.append(number)
    return tuple(found)
