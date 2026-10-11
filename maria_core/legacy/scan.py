"""Parcourt une copie de MARIA_R et prépare le rapport. N'écrit rien."""

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from maria_core.legacy.memories import convert_memories
from maria_core.legacy.model import (
    ChannelDraft,
    EmojiDraft,
    GuildDraft,
    ImportPlan,
    PollDraft,
    Skip,
)
from maria_core.legacy.read import count_rows, load
from maria_core.legacy.settings import (
    channel_draft,
    channel_guilds,
    emoji_draft,
    guild_draft,
    poll_draft,
)
from maria_core.legacy.tasks import convert_tasks

_GUILD_FILE = re.compile(r"^guild_(\d+)\.db$")
_CHANNEL_FILE = re.compile(r"^textchannel_(\d+)\.db$")
_RETIRED = (
    ("funstat.db", "fun stats retirées"),
    ("bookmarks.db", "signets retirés"),
    ("activity.db", "activité journalière non convertie"),
    ("dyn_widgets.db", "widgets éphémères non repris"),
    ("rappels.db", "ancienne base déjà absorbée par les tâches"),
)


def scan(root: Path, *, now: datetime) -> ImportPlan:
    if not root.is_dir():
        return ImportPlan(str(root), True, (), (), (), (), (), (), (), (), (), ())
    data = root / "data"
    absent: list[str] = []
    ignored: list[str] = []
    tasks = _table(root, data / "tasks.db", "tasks", absent)
    objectives, skips = convert_tasks(
        tasks, _table(root, data / "tasks.db", "member_vars", []), now=now
    )
    _note_runs(root, data / "tasks.db", ignored)
    memories, proposals, memory_skips = convert_memories(
        _table(root, data / "memories.db", "memories", absent), now=now
    )
    guilds, channels, setting_skips = _settings(root, _guilds_of(tasks, data), absent)
    emojis, emoji_skips = _emojis(root, data / "emoji_usage.db", absent, now)
    polls, poll_skips = _polls(root, data / "polls.db", absent)
    _retired(root, data, ignored)
    return ImportPlan(
        str(root),
        False,
        objectives,
        memories,
        proposals,
        tuple(guilds),
        tuple(channels),
        tuple(emojis),
        tuple(polls),
        tuple([*skips, *memory_skips, *setting_skips, *emoji_skips, *poll_skips]),
        tuple(ignored),
        tuple(absent),
    )


def _settings(
    root: Path,
    guilds_by_channel: dict[int, set[int]],
    absent: list[str],
) -> tuple[list[GuildDraft], list[ChannelDraft], list[Skip]]:
    folder = root / "cogs" / "chat" / "data"
    if not folder.is_dir():
        absent.append("cogs/chat/data")
        return [], [], []
    guilds: list[GuildDraft] = []
    channels: list[ChannelDraft] = []
    skips: list[Skip] = []
    for path in sorted(folder.glob("*.db")):
        _one_setting(path, guilds_by_channel, guilds, channels, skips)
    return guilds, channels, skips


def _one_setting(
    path: Path,
    guilds_by_channel: dict[int, set[int]],
    guilds: list[GuildDraft],
    channels: list[ChannelDraft],
    skips: list[Skip],
) -> None:
    guild_match = _GUILD_FILE.fullmatch(path.name)
    if guild_match:
        built = guild_draft(int(guild_match.group(1)), load(path, "guild_config") or [])
        _keep(built, guilds, skips)
        return
    channel_match = _CHANNEL_FILE.fullmatch(path.name)
    if channel_match is None:
        skips.append(Skip("réglage", path.name, "fichier de cog non repris"))
        return
    channel_id = int(channel_match.group(1))
    found = guilds_by_channel.get(channel_id, set())
    if len(found) > 1:
        skips.append(Skip("salon", str(channel_id), "serveur ambigu"))
        return
    guild_id = next(iter(found)) if found else None
    built_channel = channel_draft(channel_id, load(path, "channel_config") or [], guild_id)
    _keep(built_channel, channels, skips)


def _emojis(
    root: Path, path: Path, absent: list[str], now: datetime
) -> tuple[list[EmojiDraft], list[Skip]]:
    rows = _table(root, path, "emoji_stats", absent)
    merged: dict[tuple[int, str], EmojiDraft] = {}
    skips: list[Skip] = []
    for row in rows or []:
        built = emoji_draft(row, now=now)
        if isinstance(built, Skip):
            skips.append(built)
            continue
        key = (built.guild_id, built.emoji)
        current = merged.get(key)
        if current is None or built.uses > current.uses:
            merged[key] = built
    return list(merged.values()), skips


def _polls(root: Path, path: Path, absent: list[str]) -> tuple[list[PollDraft], list[Skip]]:
    drafts: list[PollDraft] = []
    skips: list[Skip] = []
    for row in _table(root, path, "polls", absent) or []:
        built = poll_draft(row)
        _keep(built, drafts, skips)
    return drafts, skips


def _guilds_of(tasks: list[sqlite3.Row] | None, data: Path) -> dict[int, set[int]]:
    found = channel_guilds(tasks)
    for channel, guilds in channel_guilds(load(data / "polls.db", "polls")).items():
        found.setdefault(channel, set()).update(guilds)
    return found


def _retired(root: Path, data: Path, ignored: list[str]) -> None:
    for name, reason in _RETIRED:
        path = data / name
        if path.is_file():
            ignored.append(f"{_relative(root, path)} : {_rows(count_rows(path))}, {reason}")


def _note_runs(root: Path, path: Path, ignored: list[str]) -> None:
    rows = load(path, "task_runs")
    if rows:
        ignored.append(
            f"{_relative(root, path)} task_runs : {_rows(len(rows))}, historique non repris"
        )


def _table(
    root: Path,
    path: Path,
    table: str,
    absent: list[str],
) -> list[sqlite3.Row] | None:
    if path.is_file():
        return load(path, table) or []
    absent.append(_relative(root, path))
    return None


def _keep[T](built: T | Skip, kept: list[T], skips: list[Skip]) -> None:
    if isinstance(built, Skip):
        skips.append(built)
    else:
        kept.append(built)


def _rows(count: int) -> str:
    if count == 1:
        return "1 ligne"
    return f"{count} lignes"


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name
