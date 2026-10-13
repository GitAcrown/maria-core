"""Écrit un plan déjà validé. La source n'est pas rouverte."""

import json
from datetime import datetime

from maria_core.db import Database
from maria_core.legacy.model import (
    ApplyResult,
    ChannelDraft,
    EmojiDraft,
    GuildDraft,
    ImportPlan,
    MemoryDraft,
    ObjectiveDraft,
    PollDraft,
    ProposalDraft,
)


def apply(database: Database, plan: ImportPlan, *, now: datetime) -> ApplyResult:
    stamp = now.isoformat()
    with database.transaction():
        counts = (
            _objectives(database, plan, stamp),
            _memories(database, plan),
            _proposals(database, plan),
            _guilds(database, plan, stamp),
            _channels(database, plan),
            _emojis(database, plan),
            _polls(database, plan),
        )
    return ApplyResult(sum(item[0] for item in counts), sum(item[1] for item in counts))


def _objectives(database: Database, plan: ImportPlan, stamp: str) -> tuple[int, int]:
    inserted = already = 0
    for item in plan.objectives:
        if _known(database, "task", item.legacy_id):
            already += 1
            continue
        _insert_objective(database, item, stamp)
        inserted += 1
    return inserted, already


def _insert_objective(database: Database, item: ObjectiveDraft, stamp: str) -> None:
    result = database.execute(
        """
        INSERT INTO objectives (
            owner_id, guild_id, channel_ids, deliver, title, trigger_json, condition_json,
            action_json, status, next_run_at, fires, max_fires, cooldown_s, expires_at,
            state_json, version, last_error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, '', ?, ?)
        """,
        (
            item.owner_id,
            item.guild_id,
            json.dumps(list(item.channel_ids)),
            item.deliver,
            item.title,
            json.dumps(item.trigger, ensure_ascii=False),
            json.dumps(item.condition, ensure_ascii=False) if item.condition else None,
            json.dumps(item.action, ensure_ascii=False),
            item.status,
            item.next_run_at,
            item.fires,
            item.max_fires,
            item.cooldown_s,
            item.expires_at,
            json.dumps(item.state, ensure_ascii=False),
            item.created_at,
            stamp,
        ),
    )
    _remember(database, "task", item.legacy_id, "objectives", result.lastrowid)


def _memories(database: Database, plan: ImportPlan) -> tuple[int, int]:
    inserted = already = 0
    for item in plan.memories:
        if _known(database, "memory", item.legacy_id):
            already += 1
            continue
        _insert_memory(database, item)
        inserted += 1
    return inserted, already


def _insert_memory(database: Database, item: MemoryDraft) -> None:
    chroma = item.chroma_id.strip() or None
    result = database.execute(
        """
        INSERT INTO memories (
            scope, subject_id, guild_id, content, source, created_by,
            created_at, updated_at, chroma_id
        ) VALUES (?, ?, ?, ?, 'imported', ?, ?, ?, ?)
        """,
        (
            item.scope,
            item.subject_id,
            item.guild_id,
            item.content,
            item.created_by,
            item.created_at,
            item.created_at,
            chroma,
        ),
    )
    database.execute(
        """
        INSERT INTO memory_revisions (memory_id, content, editor_id, reason, created_at)
        VALUES (?, ?, ?, 'importé', ?)
        """,
        (result.lastrowid, item.content, item.created_by, item.created_at),
    )
    _remember(database, "memory", item.legacy_id, "memories", result.lastrowid)


def _proposals(database: Database, plan: ImportPlan) -> tuple[int, int]:
    inserted = already = 0
    for item in plan.proposals:
        if _known(database, "proposal", item.legacy_id):
            already += 1
            continue
        _insert_proposal(database, item)
        inserted += 1
    return inserted, already


def _insert_proposal(database: Database, item: ProposalDraft) -> None:
    result = database.execute(
        """
        INSERT INTO memory_proposals (
            guild_id, subject_user_id, scope, content, confidence, status, created_at
        ) VALUES (?, ?, ?, ?, ?, 'open', ?)
        """,
        (
            item.guild_id,
            item.subject_user_id,
            item.scope,
            item.content,
            item.confidence,
            item.created_at,
        ),
    )
    _remember(database, "proposal", item.legacy_id, "memory_proposals", result.lastrowid)


def _guilds(database: Database, plan: ImportPlan, stamp: str) -> tuple[int, int]:
    inserted = already = 0
    for item in plan.guilds:
        if _known(database, "guild", str(item.guild_id)):
            already += 1
            continue
        _insert_guild(database, item, stamp)
        inserted += 1
    return inserted, already


def _insert_guild(database: Database, item: GuildDraft, stamp: str) -> None:
    database.execute(
        """
        INSERT INTO guild_settings (
            guild_id, mode, spontaneity, python_enabled, updated_at
        ) VALUES (?, ?, 'normal', 0, ?)
        ON CONFLICT(guild_id) DO UPDATE SET mode = excluded.mode, updated_at = excluded.updated_at
        """,
        (item.guild_id, item.mode, stamp),
    )
    _remember(database, "guild", str(item.guild_id), "guild_settings", item.guild_id)


def _channels(database: Database, plan: ImportPlan) -> tuple[int, int]:
    inserted = already = 0
    for item in plan.channels:
        if _known(database, "channel", str(item.channel_id)):
            already += 1
            continue
        _insert_channel(database, item)
        inserted += 1
    return inserted, already


def _insert_channel(database: Database, item: ChannelDraft) -> None:
    database.execute(
        """
        INSERT INTO channel_settings (channel_id, guild_id, respond_everyone, auto_transcribe)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            guild_id = excluded.guild_id,
            respond_everyone = excluded.respond_everyone,
            auto_transcribe = excluded.auto_transcribe
        """,
        (item.channel_id, item.guild_id, item.respond_everyone, item.auto_transcribe),
    )
    _remember(database, "channel", str(item.channel_id), "channel_settings", item.channel_id)


def _emojis(database: Database, plan: ImportPlan) -> tuple[int, int]:
    inserted = already = 0
    for item in plan.emojis:
        if _known(database, "emoji", item.legacy_id):
            already += 1
            continue
        _insert_emoji(database, item)
        inserted += 1
    return inserted, already


def _insert_emoji(database: Database, item: EmojiDraft) -> None:
    database.execute(
        """
        INSERT INTO emoji_usage (guild_id, emoji, uses, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, emoji) DO UPDATE SET
            uses = excluded.uses, updated_at = excluded.updated_at
        """,
        (item.guild_id, item.emoji, item.uses, item.updated_at),
    )
    _remember(database, "emoji", item.legacy_id, "emoji_usage", item.guild_id)


def _polls(database: Database, plan: ImportPlan) -> tuple[int, int]:
    inserted = already = 0
    for item in plan.polls:
        if _known(database, "poll", str(item.message_id)):
            already += 1
            continue
        if _insert_poll(database, item):
            inserted += 1
        else:
            already += 1
    return inserted, already


def _insert_poll(database: Database, item: PollDraft) -> bool:
    existing = database.fetchone("SELECT 1 FROM polls WHERE message_id = ?", (item.message_id,))
    if existing is not None:
        _remember(database, "poll", str(item.message_id), "polls", item.message_id)
        return False
    database.execute(
        """
        INSERT INTO polls (
            message_id, channel_id, guild_id, author_id, question,
            options_json, expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.message_id,
            item.channel_id,
            item.guild_id,
            item.author_id,
            item.question,
            json.dumps(list(item.options), ensure_ascii=False),
            item.expires_at,
            item.created_at,
        ),
    )
    _remember(database, "poll", str(item.message_id), "polls", item.message_id)
    return True


def _known(database: Database, source: str, legacy_id: str) -> bool:
    row = database.fetchone(
        "SELECT 1 FROM legacy_map WHERE source = ? AND legacy_id = ?",
        (source, legacy_id),
    )
    return row is not None


def _remember(
    database: Database, source: str, legacy_id: str, destination: str, row_id: int
) -> None:
    database.execute(
        """
        INSERT INTO legacy_map (source, legacy_id, destination, row_id)
        VALUES (?, ?, ?, ?)
        """,
        (source, legacy_id, destination, row_id),
    )
