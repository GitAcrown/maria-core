"""SQLite et FTS5. Une proposition n'est pas un souvenir tant qu'elle n'est pas acceptée."""

import sqlite3
from datetime import UTC, datetime, timedelta

from maria_core.db import Database
from maria_core.memory.model import Memory, Proposal
from maria_core.memory.policy import Actor, denial
from maria_core.memory.text import close, match_query, normalize
from maria_core.vectors.index import VectorIndex

PROPOSAL_DAYS = 14
PURGE_AFTER = timedelta(days=30)
_ASK_GAP = timedelta(hours=1)


class MemoryDenied(Exception):
    """L'acteur n'a pas le droit d'écrire ce souvenir."""


class MemoryStore:
    def __init__(self, database: Database, index: VectorIndex) -> None:
        self._database = database
        self._index = index

    def remember(
        self,
        actor: Actor,
        *,
        scope: str,
        subject_id: int,
        guild_id: int | None,
        content: str,
        source: str,
        now: datetime,
    ) -> Memory:
        refused = denial(actor, scope, subject_id)
        if refused:
            raise MemoryDenied(refused)
        text = content.strip()
        if not text:
            raise ValueError("Souvenir vide.")
        current = self._similar(scope, subject_id, guild_id, text)
        if current is None:
            return self._insert(actor, scope, subject_id, guild_id, text, source, now, "création")
        if normalize(current.content) == normalize(text):
            return current
        return self._rewrite(current, text, actor.user_id, "mise à jour", now)

    def forget(self, actor: Actor, memory_id: int, now: datetime) -> bool:
        current = self.get(memory_id)
        if current is None or current.deleted_at is not None:
            return False
        if denial(actor, current.scope, current.subject_id):
            raise MemoryDenied("Tu ne peux pas effacer ce souvenir.")
        self._database.execute(
            "UPDATE memories SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now.isoformat(), now.isoformat(), memory_id),
        )
        self._revise(memory_id, current.content, actor.user_id, "suppression", now)
        self._index.delete(memory_id)
        return True

    def undo(self, actor: Actor, memory_id: int, now: datetime) -> Memory | None:
        current = self.get(memory_id)
        if current is None:
            return None
        if denial(actor, current.scope, current.subject_id):
            raise MemoryDenied("Tu ne peux pas annuler ce souvenir.")
        previous = self._previous(memory_id)
        if previous is None or current.deleted_at is not None:
            self.forget(actor, memory_id, now)
            return None
        return self._rewrite(current, previous, actor.user_id, "annulation", now)

    def get(self, memory_id: int) -> Memory | None:
        row = self._database.fetchone("SELECT * FROM memories WHERE id = ?", (memory_id,))
        if row is None:
            return None
        return _memory(row)

    def search(
        self,
        query: str,
        *,
        user_id: int,
        guild_id: int | None,
        mentioned: tuple[int, ...] = (),
        limit: int = 4,
    ) -> tuple[Memory, ...]:
        match = match_query(query)
        if not match:
            return ()
        rows = self._database.fetchall(
            """
            SELECT memories.* FROM memories
            JOIN memories_fts ON memories.id = memories_fts.rowid
            WHERE memories_fts MATCH ? AND memories.deleted_at IS NULL
            LIMIT 20
            """,
            (match,),
        )
        visible = [
            _memory(row) for row in rows if _visible(_memory(row), user_id, guild_id, mentioned)
        ]
        return tuple(visible[:limit])

    def profile(self, user_id: int, *, limit: int = 3) -> tuple[Memory, ...]:
        rows = self._database.fetchall(
            """
            SELECT * FROM memories
            WHERE deleted_at IS NULL AND scope = 'user' AND subject_id = ?
            ORDER BY COALESCE(last_used_at, updated_at) DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return tuple(_memory(row) for row in rows)

    def list_for(self, user_id: int) -> tuple[Memory, ...]:
        return self.profile(user_id, limit=20)

    def list_guild(self, guild_id: int) -> tuple[Memory, ...]:
        rows = self._database.fetchall(
            """
            SELECT * FROM memories
            WHERE deleted_at IS NULL AND scope = 'guild' AND guild_id = ?
            ORDER BY updated_at DESC LIMIT 20
            """,
            (guild_id,),
        )
        return tuple(_memory(row) for row in rows)

    def mark_used(self, memory_ids: tuple[int, ...], now: datetime) -> None:
        for memory_id in memory_ids:
            self._database.execute(
                "UPDATE memories SET last_used_at = ? WHERE id = ? AND deleted_at IS NULL",
                (now.isoformat(), memory_id),
            )

    def count_active(self) -> int:
        row = self._database.fetchone("SELECT COUNT(*) AS n FROM memories WHERE deleted_at IS NULL")
        return 0 if row is None else int(row["n"])

    def propose(
        self,
        *,
        scope: str,
        content: str,
        subject_user_id: int | None,
        guild_id: int | None,
        channel_id: int | None,
        source_message_id: int | None,
        now: datetime,
    ) -> Proposal:
        result = self._database.execute(
            """
            INSERT INTO memory_proposals (
                guild_id, channel_id, subject_user_id, scope, content, status,
                source_message_id, created_at
            ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                guild_id,
                channel_id,
                subject_user_id,
                scope,
                content.strip(),
                source_message_id,
                now.isoformat(),
            ),
        )
        proposal = self.proposal(result.lastrowid)
        if proposal is None:
            raise RuntimeError("Proposition introuvable.")
        return proposal

    def proposal(self, proposal_id: int) -> Proposal | None:
        row = self._database.fetchone(
            "SELECT * FROM memory_proposals WHERE id = ?",
            (proposal_id,),
        )
        return None if row is None else _proposal(row)

    def open_for(self, user_id: int) -> tuple[Proposal, ...]:
        rows = self._database.fetchall(
            """
            SELECT * FROM memory_proposals
            WHERE status = 'open' AND subject_user_id = ?
            ORDER BY created_at DESC LIMIT 10
            """,
            (user_id,),
        )
        return tuple(_proposal(row) for row in rows)

    def accept(self, proposal_id: int, actor: Actor, now: datetime) -> Memory:
        proposal = self._open_owned(proposal_id, actor)
        subject = _accepted_subject(proposal, actor)
        memory = self.remember(
            actor,
            scope=proposal.scope,
            subject_id=subject,
            guild_id=proposal.guild_id,
            content=proposal.content,
            source="confirmed",
            now=now,
        )
        self._resolve(proposal_id, "accepted", now, memory.id)
        return memory

    def ignore(self, proposal_id: int, actor: Actor, now: datetime) -> None:
        self._open_owned(proposal_id, actor)
        self._resolve(proposal_id, "ignored", now, None)

    def confirm_repeat(self, actor: Actor, text: str, now: datetime) -> bool:
        for proposal in self.open_for(actor.user_id):
            if proposal.scope == "user" and close(proposal.content, text):
                self.accept(proposal.id, actor, now)
                return True
        return False

    def asked_recently(self, user_id: int, now: datetime) -> bool:
        row = self._database.fetchone(
            """
            SELECT created_at FROM memory_proposals
            WHERE subject_user_id = ? AND status = 'open'
            ORDER BY created_at DESC LIMIT 1
            """,
            (user_id,),
        )
        if row is None:
            return False
        created = _time(row["created_at"])
        return created is not None and now - created < _ASK_GAP

    def attach_reply(self, proposal_id: int, message_id: int) -> None:
        self._database.execute(
            "UPDATE memory_proposals SET reply_message_id = ? WHERE id = ?",
            (message_id, proposal_id),
        )

    def restorable(self) -> tuple[Proposal, ...]:
        rows = self._database.fetchall(
            """
            SELECT * FROM memory_proposals
            WHERE status = 'open' AND reply_message_id IS NOT NULL
            ORDER BY created_at DESC LIMIT 30
            """
        )
        return tuple(_proposal(row) for row in rows)

    def maintain(self, now: datetime) -> None:
        limit = (now - timedelta(days=PROPOSAL_DAYS)).isoformat()
        self._database.execute(
            """
            UPDATE memory_proposals
            SET status = 'expired', resolved_at = ?
            WHERE status = 'open' AND created_at < ?
            """,
            (now.isoformat(), limit),
        )
        cutoff = (now - PURGE_AFTER).isoformat()
        self._database.execute(
            """
            DELETE FROM memory_revisions WHERE memory_id IN (
                SELECT id FROM memories WHERE deleted_at IS NOT NULL AND deleted_at < ?
            )
            """,
            (cutoff,),
        )
        self._database.execute(
            """
            UPDATE memory_proposals SET memory_id = NULL WHERE memory_id IN (
                SELECT id FROM memories WHERE deleted_at IS NOT NULL AND deleted_at < ?
            )
            """,
            (cutoff,),
        )
        self._database.execute(
            "DELETE FROM memories WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff,),
        )

    def propose_stale(self, now: datetime, *, older_than: timedelta) -> int:
        cutoff = (now - older_than).isoformat()
        rows = self._database.fetchall(
            """
            SELECT * FROM memories
            WHERE deleted_at IS NULL AND updated_at < ?
              AND (last_used_at IS NULL OR last_used_at < ?)
            LIMIT 20
            """,
            (cutoff, cutoff),
        )
        created = 0
        for row in rows:
            memory = _memory(row)
            if self._pending_same(memory):
                continue
            self.propose(
                scope=memory.scope,
                content=memory.content,
                subject_user_id=memory.subject_id if memory.scope == "user" else None,
                guild_id=memory.guild_id,
                channel_id=None,
                source_message_id=None,
                now=now,
            )
            created += 1
        return created

    def _similar(
        self,
        scope: str,
        subject_id: int,
        guild_id: int | None,
        text: str,
    ) -> Memory | None:
        rows = self._database.fetchall(
            """
            SELECT * FROM memories
            WHERE deleted_at IS NULL AND scope = ? AND subject_id = ?
              AND (guild_id IS ? OR guild_id = ?)
            """,
            (scope, subject_id, guild_id, guild_id),
        )
        for row in rows:
            memory = _memory(row)
            if close(memory.content, text):
                return memory
        return None

    def _insert(
        self,
        actor: Actor,
        scope: str,
        subject_id: int,
        guild_id: int | None,
        text: str,
        source: str,
        now: datetime,
        reason: str,
    ) -> Memory:
        stamp = now.isoformat()
        result = self._database.execute(
            """
            INSERT INTO memories (
                scope, subject_id, guild_id, content, source, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (scope, subject_id, guild_id, text, source, actor.user_id, stamp, stamp),
        )
        self._revise(result.lastrowid, text, actor.user_id, reason, now)
        self._index.upsert(result.lastrowid, text)
        saved = self.get(result.lastrowid)
        if saved is None:
            raise RuntimeError("Souvenir introuvable.")
        return saved

    def _rewrite(
        self, current: Memory, text: str, editor_id: int, reason: str, now: datetime
    ) -> Memory:
        self._database.execute(
            "UPDATE memories SET content = ?, updated_at = ?, deleted_at = NULL WHERE id = ?",
            (text, now.isoformat(), current.id),
        )
        self._revise(current.id, text, editor_id, reason, now)
        self._index.upsert(current.id, text)
        saved = self.get(current.id)
        if saved is None:
            raise RuntimeError("Souvenir introuvable.")
        return saved

    def _revise(
        self, memory_id: int, content: str, editor_id: int, reason: str, now: datetime
    ) -> None:
        self._database.execute(
            """
            INSERT INTO memory_revisions (memory_id, content, editor_id, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (memory_id, content, editor_id, reason, now.isoformat()),
        )

    def _previous(self, memory_id: int) -> str | None:
        rows = self._database.fetchall(
            """
            SELECT content FROM memory_revisions
            WHERE memory_id = ? ORDER BY id DESC LIMIT 2
            """,
            (memory_id,),
        )
        if len(rows) < 2:
            return None
        return str(rows[1]["content"])

    def _open_owned(self, proposal_id: int, actor: Actor) -> Proposal:
        proposal = self.proposal(proposal_id)
        if proposal is None or proposal.status != "open":
            raise ValueError("Proposition introuvable.")
        subject = proposal.subject_user_id
        if subject not in {None, actor.user_id} and not actor.is_owner and not actor.is_moderator:
            raise MemoryDenied("Cette proposition ne t'est pas adressée.")
        return proposal

    def _resolve(self, proposal_id: int, status: str, now: datetime, memory_id: int | None) -> None:
        self._database.execute(
            """
            UPDATE memory_proposals
            SET status = ?, resolved_at = ?, memory_id = ?
            WHERE id = ?
            """,
            (status, now.isoformat(), memory_id, proposal_id),
        )

    def _pending_same(self, memory: Memory) -> bool:
        rows = self._database.fetchall(
            """
            SELECT content FROM memory_proposals
            WHERE status = 'open' AND scope = ? AND content = ?
            """,
            (memory.scope, memory.content),
        )
        return bool(rows)


def _accepted_subject(proposal: Proposal, actor: Actor) -> int:
    if proposal.scope == "guild":
        return proposal.guild_id or 0
    if proposal.scope == "self":
        return 0
    return proposal.subject_user_id or actor.user_id


def _visible(
    memory: Memory, user_id: int, guild_id: int | None, mentioned: tuple[int, ...]
) -> bool:
    if memory.scope == "self":
        return True
    if memory.scope == "guild":
        return guild_id is not None and memory.guild_id == guild_id
    allowed = {user_id, *mentioned}
    return memory.scope == "user" and memory.subject_id in allowed


def _memory(row: sqlite3.Row) -> Memory:
    return Memory(
        id=int(row["id"]),
        scope=str(row["scope"]),
        subject_id=int(row["subject_id"]),
        guild_id=int(row["guild_id"]) if row["guild_id"] is not None else None,
        content=str(row["content"]),
        source=str(row["source"]),
        created_by=int(row["created_by"]),
        created_at=_required(row["created_at"]),
        updated_at=_required(row["updated_at"]),
        last_used_at=_time(row["last_used_at"]),
        deleted_at=_time(row["deleted_at"]),
    )


def _proposal(row: sqlite3.Row) -> Proposal:
    return Proposal(
        id=int(row["id"]),
        guild_id=int(row["guild_id"]) if row["guild_id"] is not None else None,
        channel_id=int(row["channel_id"]) if row["channel_id"] is not None else None,
        subject_user_id=int(row["subject_user_id"]) if row["subject_user_id"] is not None else None,
        scope=str(row["scope"]),
        content=str(row["content"]),
        status=str(row["status"]),
        created_at=_required(row["created_at"]),
        reply_message_id=int(row["reply_message_id"])
        if row["reply_message_id"] is not None
        else None,
    )


def _required(raw: object) -> datetime:
    parsed = _time(raw)
    if parsed is None:
        raise ValueError("Date de souvenir manquante.")
    return parsed


def _time(raw: object) -> datetime | None:
    if not raw:
        return None
    moment = datetime.fromisoformat(str(raw))
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment
