"""Purge des journaux techniques. Ne touche ni aux souvenirs ni aux objectifs."""

from datetime import datetime, timedelta

from maria_core.db.database import Database

_DECISIONS_DAYS = 30
_CALLS_DAYS = 90
_SPONTANEITY_DAYS = 14
_ACTIVITY_DAYS = 21
_BUDGET_HOURS = 48
_RUN_DAYS = 60


def purge(database: Database, now: datetime) -> dict[str, int]:
    """Renvoie le nombre de lignes retirées par table."""

    def before(**delta: float) -> str:
        return (now - timedelta(**delta)).isoformat()

    statements = {
        "decision_log": ("DELETE FROM decision_log WHERE at < ?", before(days=_DECISIONS_DAYS)),
        "llm_calls": ("DELETE FROM llm_calls WHERE at < ?", before(days=_CALLS_DAYS)),
        "capability_calls": (
            "DELETE FROM capability_calls WHERE at < ?",
            before(days=_CALLS_DAYS),
        ),
        "spontaneity_log": (
            "DELETE FROM spontaneity_log WHERE at < ?",
            before(days=_SPONTANEITY_DAYS),
        ),
        "guild_hour_activity": (
            "DELETE FROM guild_hour_activity WHERE day < ?",
            (now - timedelta(days=_ACTIVITY_DAYS)).date().isoformat(),
        ),
        "social_budget": (
            "DELETE FROM social_budget WHERE hour_key < ?",
            (now - timedelta(hours=_BUDGET_HOURS)).strftime("%Y-%m-%dT%H"),
        ),
        "objective_fetches": (
            "DELETE FROM objective_fetches WHERE at < ?",
            before(days=3),
        ),
        "member_seen": ("DELETE FROM member_seen WHERE last_at < ?", before(days=14)),
        "objective_runs": (
            "DELETE FROM objective_runs WHERE finished_at IS NOT NULL AND finished_at < ?",
            before(days=_RUN_DAYS),
        ),
    }
    removed: dict[str, int] = {}
    with database.transaction():
        for table, (sql, cutoff) in statements.items():
            removed[table] = database.execute(sql, (cutoff,)).rowcount
    database.execute("PRAGMA optimize")
    return removed
