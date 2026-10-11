"""Seuil ajusté à l'habitude du serveur, à cette heure-ci, sur deux semaines."""

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from maria_core.db import Database

PARIS = ZoneInfo("Europe/Paris")
_HISTORY_DAYS = 14
_MIN_DAYS = 3
_SHIFT = 0.2


def record(database: Database, guild_id: int, now: datetime) -> None:
    local = now.astimezone(PARIS)
    database.execute(
        """
        INSERT INTO guild_hour_activity (guild_id, day, hour, messages)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(guild_id, day, hour) DO UPDATE SET messages = messages + 1
        """,
        (guild_id, local.date().isoformat(), local.hour),
    )


def threshold(database: Database, guild_id: int, now: datetime, base: float) -> float:
    local = now.astimezone(PARIS)
    usual = _usual(database, guild_id, local.date(), local.hour)
    current = _today(database, guild_id, local.date().isoformat(), local.hour)
    return adjust(base, usual, current, local.minute)


def adjust(base: float, usual: float | None, current: int, minute: int) -> float:
    """Plus chargé que d'habitude : seuil plus haut. Plus calme : seuil plus bas."""
    if usual is None or usual < 1:
        return base
    elapsed = max(minute + 1, 15)
    projected = current * 60 / elapsed
    ratio = 0.25 if projected <= 0 else projected / usual
    shift = max(-1.0, min(1.0, math.log2(ratio))) * _SHIFT
    return max(0.2, min(0.95, base + shift))


def _usual(database: Database, guild_id: int, today, hour: int) -> float | None:
    start = (today - timedelta(days=_HISTORY_DAYS)).isoformat()
    rows = database.fetchall(
        """
        SELECT messages FROM guild_hour_activity
        WHERE guild_id = ? AND hour = ? AND day >= ? AND day < ?
        """,
        (guild_id, hour, start, today.isoformat()),
    )
    if len(rows) < _MIN_DAYS:
        return None
    return sum(int(row["messages"]) for row in rows) / len(rows)


def _today(database: Database, guild_id: int, day: str, hour: int) -> int:
    row = database.fetchone(
        """
        SELECT messages FROM guild_hour_activity
        WHERE guild_id = ? AND day = ? AND hour = ?
        """,
        (guild_id, day, hour),
    )
    return 0 if row is None else int(row["messages"])
