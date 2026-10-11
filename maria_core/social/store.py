"""Budget, emojis appris, journal. Relu après un redémarrage."""

import json
from datetime import UTC, datetime

from maria_core.db import Database
from maria_core.social.score import Parts

SOCIAL_NAMES = ("ambient_react", "pick_reaction", "join_reaction", "followup")
DAILY_DECISIONS = 80


class SocialStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    def reactions_this_hour(self, channel_id: int, hour_key: str) -> tuple[int, int | None]:
        row = self._database.fetchone(
            """
            SELECT reactions, last_author_id FROM social_budget
            WHERE channel_id = ? AND hour_key = ?
            """,
            (channel_id, hour_key),
        )
        if row is None:
            return 0, None
        last = int(row["last_author_id"]) if row["last_author_id"] is not None else None
        return int(row["reactions"]), last

    def mark_reaction(self, channel_id: int, hour_key: str, author_id: int) -> None:
        self._database.execute(
            """
            INSERT INTO social_budget (channel_id, hour_key, reactions, last_author_id)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(channel_id, hour_key) DO UPDATE SET
                reactions = reactions + 1,
                last_author_id = excluded.last_author_id
            """,
            (channel_id, hour_key, author_id),
        )

    def learn(self, guild_id: int, emoji: str, now: datetime) -> None:
        self._database.execute(
            """
            INSERT INTO emoji_usage (guild_id, emoji, uses, updated_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(guild_id, emoji) DO UPDATE SET
                uses = uses + 1,
                updated_at = excluded.updated_at
            """,
            (guild_id, emoji, now.isoformat()),
        )

    def top_emojis(self, guild_id: int, limit: int = 3) -> tuple[str, ...]:
        rows = self._database.fetchall(
            """
            SELECT emoji FROM emoji_usage
            WHERE guild_id = ? ORDER BY uses DESC, emoji LIMIT ?
            """,
            (guild_id, limit),
        )
        return tuple(str(row["emoji"]) for row in rows)

    def log(
        self,
        *,
        now: datetime,
        guild_id: int | None,
        channel_id: int,
        message_id: int,
        author_id: int,
        parts: Parts,
        verdict: str,
        emoji: str = "",
        threshold: float | None = None,
    ) -> None:
        payload = parts.as_dict()
        if threshold is not None:
            payload["seuil"] = round(threshold, 3)
        self._database.execute(
            """
            INSERT INTO spontaneity_log (
                at, guild_id, channel_id, message_id, author_id, score, parts_json, verdict, emoji
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now.isoformat(),
                guild_id,
                channel_id,
                message_id,
                author_id,
                parts.total(),
                json.dumps(payload, ensure_ascii=False),
                verdict,
                emoji,
            ),
        )

    def explain(self, message_id: int) -> str:
        row = self._database.fetchone(
            """
            SELECT score, parts_json, verdict, emoji FROM spontaneity_log
            WHERE message_id = ? ORDER BY id DESC LIMIT 1
            """,
            (message_id,),
        )
        if row is None:
            return "Aucun passage sur ce message."
        parts = json.loads(row["parts_json"])
        detail = ", ".join(f"{key} {parts[key]}" for key in parts if key not in {"total", "seuil"})
        emoji = f" {row['emoji']}" if row["emoji"] else ""
        limit = parts.get("seuil", "?")
        return (
            f"Score {row['score']} (seuil {limit}) — {detail}. Verdict : {row['verdict']}{emoji}."
        )

    def model_calls_today(self, now: datetime) -> int:
        start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        marks = ", ".join("?" for _ in SOCIAL_NAMES)
        row = self._database.fetchone(
            f"""
            SELECT COUNT(*) AS n FROM decision_log
            WHERE path = 'model' AND at >= ? AND name IN ({marks})
            """,
            (start.isoformat(), *SOCIAL_NAMES),
        )
        return 0 if row is None else int(row["n"])
