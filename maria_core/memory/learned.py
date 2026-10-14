"""Ce que MARIA a retenu seule : à montrer à la personne, et à pouvoir défaire."""

from datetime import datetime, timedelta

from maria_core.db import Database
from maria_core.memory.model import Memory
from maria_core.memory.rows import memory_row

RECENT_DAYS = 14
BUTTON_DAYS = 3


class LearnedLog:
    def __init__(self, database: Database) -> None:
        self._database = database

    def mark(self, memory_id: int, now: datetime) -> None:
        self._database.execute(
            "UPDATE memories SET learned_at = ? WHERE id = ?", (now.isoformat(), memory_id)
        )

    def attach_reply(self, memory_id: int, message_id: int) -> None:
        self._database.execute(
            "UPDATE memories SET learned_reply_id = ? WHERE id = ?", (message_id, memory_id)
        )

    def clear(self, memory_id: int) -> None:
        self._database.execute(
            "UPDATE memories SET learned_at = NULL, learned_reply_id = NULL WHERE id = ?",
            (memory_id,),
        )

    def recent(self, user_id: int, now: datetime, limit: int = 50) -> tuple[Memory, ...]:
        since = (now - timedelta(days=RECENT_DAYS)).isoformat()
        rows = self._database.fetchall(
            """
            SELECT * FROM memories
            WHERE scope = 'user' AND subject_id = ? AND deleted_at IS NULL
              AND learned_at IS NOT NULL AND learned_at >= ?
            ORDER BY learned_at DESC LIMIT ?
            """,
            (user_id, since, limit),
        )
        return tuple(memory_row(row) for row in rows)

    def restorable(self, now: datetime) -> tuple[tuple[int, int], ...]:
        """(souvenir, message) dont le bouton Annuler doit survivre à un redémarrage."""
        since = (now - timedelta(days=BUTTON_DAYS)).isoformat()
        rows = self._database.fetchall(
            """
            SELECT id, learned_reply_id FROM memories
            WHERE learned_reply_id IS NOT NULL AND deleted_at IS NULL AND learned_at >= ?
            ORDER BY learned_at DESC LIMIT 40
            """,
            (since,),
        )
        return tuple((int(row["id"]), int(row["learned_reply_id"])) for row in rows)
