"""Base : migration, retour arrière, transactions, recherche des souvenirs."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from maria_core.db import Database
from maria_core.errors import DatabaseError, MigrationError

_NOW = "2026-10-11T12:00:00+00:00"


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    opened = Database(tmp_path / "maria.db")
    opened.migrate()
    try:
        yield opened
    finally:
        opened.close()


def test_first_migration_creates_the_schema_without_a_backup(
    database: Database, tmp_path: Path
) -> None:
    assert database.migrate() == ()
    assert database.version == 15
    backups = sorted(path.name for path in (tmp_path / "backups").glob("*.db"))
    versions = sorted(int(name.split("-")[1][1:]) for name in backups)
    assert versions == list(range(1, 15))
    tables = {row["name"] for row in database.fetchall("SELECT name FROM sqlite_master")}
    assert "bookmarks" not in tables
    assert "widget_tabs" not in tables
    assert {
        "objectives",
        "memories",
        "decision_log",
        "llm_calls",
        "emoji_words",
        "objective_fetches",
        "polls",
        "capability_calls",
    } <= tables
    database.close()


def test_foreign_keys_are_enforced_and_a_failure_does_not_stick(database: Database) -> None:
    flag = database.fetchone("PRAGMA foreign_keys")
    assert flag is not None
    assert flag[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            """
            INSERT INTO objective_runs (objective_id, activation_key, started_at)
            VALUES (999, 'twice', ?)
            """,
            (_NOW,),
        )
    database.execute(
        """
        INSERT INTO guild_settings (guild_id, updated_at) VALUES (1, ?)
        """,
        (_NOW,),
    )
    row = database.fetchone("SELECT guild_id FROM guild_settings WHERE guild_id = 1")
    assert row is not None
    database.close()


def test_transaction_commits_or_rolls_back_as_a_whole(database: Database) -> None:
    with pytest.raises(RuntimeError, match="stop"), database.transaction():
        database.execute(
            "INSERT INTO guild_settings (guild_id, updated_at) VALUES (3, ?)",
            (_NOW,),
        )
        raise RuntimeError("stop")
    assert database.fetchone("SELECT guild_id FROM guild_settings WHERE guild_id = 3") is None

    with database.transaction():
        database.execute(
            "INSERT INTO guild_settings (guild_id, updated_at) VALUES (3, ?)",
            (_NOW,),
        )
    kept = database.fetchone("SELECT guild_id FROM guild_settings WHERE guild_id = 3")
    assert kept is not None
    database.close()


def test_soft_deleted_memory_is_not_searchable(database: Database) -> None:
    database.execute(
        """
        INSERT INTO memories (
            scope, subject_id, content, source, created_by, created_at, updated_at
        ) VALUES ('user', 7, 'Lea est vegetarienne', 'explicit', 7, ?, ?)
        """,
        (_NOW, _NOW),
    )
    query = """
        SELECT memories.id FROM memories
        JOIN memories_fts ON memories.id = memories_fts.rowid
        WHERE memories_fts MATCH 'vegetarienne' AND memories.deleted_at IS NULL
    """
    found = database.fetchall(query)
    assert len(found) == 1
    database.execute(
        "UPDATE memories SET deleted_at = ?, updated_at = ? WHERE subject_id = 7",
        (_NOW, _NOW),
    )
    assert database.fetchall(query) == []
    database.close()


def test_failed_migration_restores_the_previous_file(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_init.sql").write_text(
        "CREATE TABLE sample (id INTEGER PRIMARY KEY, label TEXT NOT NULL);\n",
        encoding="utf-8",
    )
    first = Database(tmp_path / "app" / "maria.db", migrations_dir=migrations)
    assert first.migrate() == ("001_init",)
    first.execute("INSERT INTO sample (label) VALUES ('ok')")
    first.close()

    (migrations / "002_broken.sql").write_text(
        "CREATE TABLE extra (id INTEGER PRIMARY KEY);\nNOT VALID;\n",
        encoding="utf-8",
    )
    second = Database(tmp_path / "app" / "maria.db", migrations_dir=migrations)
    with pytest.raises(MigrationError, match="002_broken"):
        second.migrate()
    assert second.version == 1
    label = second.fetchone("SELECT label FROM sample")
    assert label is not None
    assert label["label"] == "ok"
    extra = second.fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'extra'"
    )
    assert extra == []
    assert list((tmp_path / "app" / "backups").glob("maria-v1-*.db"))
    second.close()


def test_migration_names_must_be_contiguous(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "002_only.sql").write_text("SELECT 1;\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="non contigu"):
        Database(tmp_path / "maria.db", migrations_dir=migrations)


def test_closed_database_refuses_queries(database: Database) -> None:
    database.close()
    with pytest.raises(DatabaseError, match="fermée"):
        database.fetchall("SELECT 1")
    database.close()
