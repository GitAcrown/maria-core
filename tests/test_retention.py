"""Les journaux techniques ne s'accumulent pas."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from maria_core.db import Database
from maria_core.db.retention import purge


def test_old_rows_leave_and_fresh_ones_stay(tmp_path: Path) -> None:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    now = datetime(2026, 10, 11, 12, tzinfo=UTC)
    old = (now - timedelta(days=40)).isoformat()
    fresh = now.isoformat()
    database.execute(
        """
        INSERT INTO decision_log (at, name, input_hash, path, verdict, duration_ms)
        VALUES (?, 'addressed_to_bot', 'a', 'fallback', 'ignore', 1),
               (?, 'addressed_to_bot', 'b', 'rules', 'respond', 1)
        """,
        (old, fresh),
    )
    removed = purge(database, now)
    assert removed["decision_log"] == 1
    left = database.fetchone("SELECT COUNT(*) AS n FROM decision_log")
    assert left is not None
    assert left["n"] == 1
    database.close()
