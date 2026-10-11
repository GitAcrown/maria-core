"""Plafonds : objectifs ouverts par personne, lectures web par jour."""

from datetime import UTC, datetime, timedelta

from maria_core.db import Database

MAX_OPEN = 10
MAX_FETCHES_PER_DAY = 40


def open_count(database: Database, owner_id: int) -> int:
    row = database.fetchone(
        """
        SELECT COUNT(*) AS n FROM objectives
        WHERE owner_id = ? AND status IN ('draft', 'active', 'paused')
        """,
        (owner_id,),
    )
    if row is None:
        return 0
    return int(row["n"])


def fetches_today(database: Database, now: datetime) -> int:
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    row = database.fetchone(
        """
        SELECT COUNT(*) AS n FROM objective_runs AS runs
        JOIN objectives ON objectives.id = runs.objective_id
        WHERE runs.started_at >= ?
          AND runs.outcome = 'sent'
          AND objectives.action_json LIKE '%"fetch_then"%'
        """,
        (start.isoformat(),),
    )
    if row is None:
        return 0
    return int(row["n"])


def fetches_allowed(database: Database, now: datetime) -> bool:
    return fetches_today(database, now) < MAX_FETCHES_PER_DAY


def next_budget_day(now: datetime) -> datetime:
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return start + timedelta(days=1)
