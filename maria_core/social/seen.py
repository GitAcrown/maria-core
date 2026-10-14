"""Quand une personne a quitté un salon pour la dernière fois, pour lui dire ce qu'elle a raté."""

from datetime import datetime, timedelta

from maria_core.db import Database

AWAY_GAP = timedelta(minutes=30)
KEEP_DAYS = 14


class Seen:
    def __init__(self, database: Database) -> None:
        self._database = database

    def touch(self, user_id: int, channel_id: int, now: datetime) -> None:
        """Un message de la personne. Plus de 30 minutes de silence : la visite précédente finit."""
        row = self._database.fetchone(
            "SELECT last_at, away_since FROM member_seen WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        )
        away = None if row is None else row["away_since"]
        if row is not None and now - datetime.fromisoformat(row["last_at"]) > AWAY_GAP:
            away = row["last_at"]
        self._database.execute(
            """
            INSERT INTO member_seen (user_id, channel_id, last_at, away_since)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, channel_id) DO UPDATE SET
                last_at = excluded.last_at, away_since = excluded.away_since
            """,
            (user_id, channel_id, now.isoformat(), away),
        )

    def away_since(self, user_id: int, channel_id: int) -> datetime | None:
        row = self._database.fetchone(
            "SELECT away_since FROM member_seen WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        )
        if row is None or row["away_since"] is None:
            return None
        return datetime.fromisoformat(row["away_since"])

    def purge(self, now: datetime) -> int:
        cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
        return self._database.execute(
            "DELETE FROM member_seen WHERE last_at < ?", (cutoff,)
        ).rowcount
