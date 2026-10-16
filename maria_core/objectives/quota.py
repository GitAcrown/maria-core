"""Plafonds : objectifs ouverts par personne, lectures web par jour et par serveur."""

from datetime import UTC, datetime, timedelta

from maria_core.db import Database

MAX_OPEN = 10
MAX_FOR_OTHERS = 3
MAX_FETCHES_PER_DAY = 40
MIN_FETCH_INTERVAL_S = 6 * 3600
STORM_PER_HOUR = 3


def open_count(database: Database, owner_id: int) -> int:
    row = database.fetchone(
        """
        SELECT COUNT(*) AS n FROM objectives
        WHERE owner_id = ? AND status IN ('draft', 'active', 'paused')
        """,
        (owner_id,),
    )
    return 0 if row is None else int(row["n"])


def open_for_others(database: Database, owner_id: int) -> int:
    """Rappels en attente que cette personne a programmés pour quelqu'un d'autre."""
    row = database.fetchone(
        """
        SELECT COUNT(*) AS n FROM objectives
        WHERE owner_id = ? AND target_id IS NOT NULL AND target_id != owner_id
          AND status IN ('draft', 'active', 'paused')
        """,
        (owner_id,),
    )
    return 0 if row is None else int(row["n"])


def budget_key(guild_id: int | None, owner_id: int) -> str:
    return f"guild:{guild_id}" if guild_id is not None else f"user:{owner_id}"


def fetches_today(database: Database, key: str, now: datetime) -> int:
    row = database.fetchone(
        "SELECT COUNT(*) AS n FROM objective_fetches WHERE budget_key = ? AND at >= ?",
        (key, _day_start(now).isoformat()),
    )
    return 0 if row is None else int(row["n"])


def take_fetch(database: Database, objective_id: int, key: str, now: datetime) -> bool:
    """Réserve une lecture web. Chaque lecture compte, que la condition soit vraie ou non."""
    with database.transaction():
        if fetches_today(database, key, now) >= MAX_FETCHES_PER_DAY:
            return False
        database.execute(
            "INSERT INTO objective_fetches (at, objective_id, budget_key) VALUES (?, ?, ?)",
            (now.isoformat(), objective_id, key),
        )
    return True


def fires_last_hour(database: Database, objective_id: int, now: datetime) -> int:
    row = database.fetchone(
        """
        SELECT COUNT(*) AS n FROM objective_runs
        WHERE objective_id = ? AND outcome = 'sent' AND started_at >= ?
        """,
        (objective_id, (now - timedelta(hours=1)).isoformat()),
    )
    return 0 if row is None else int(row["n"])


def next_budget_day(now: datetime) -> datetime:
    return _day_start(now) + timedelta(days=1)


def _day_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
