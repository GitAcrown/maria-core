"""Import MARIA_R : le rapport précède l'écriture, la source reste intacte."""

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from maria_core.db import Database
from maria_core.db.database import DEFAULT_MIGRATIONS
from maria_core.legacy import apply, render, scan
from maria_core.legacy.__main__ import main
from maria_core.objectives.store import ObjectiveStore

_NOW = datetime(2026, 10, 11, 18, 0, tzinfo=UTC)


def test_the_report_lists_what_cannot_be_converted(tmp_path: Path) -> None:
    root = _legacy(tmp_path)
    text = render(scan(root, now=_NOW))
    assert "recherche web non portée" not in text
    assert "signal Discord ciblé non porté" not in text
    assert "statut terminal" in text
    assert "fun stats retirées" in text
    assert "signets retirés" in text
    assert "Aucune écriture" not in text
    assert not (tmp_path / "maria.db").exists()


def test_write_copies_only_convertible_rows_and_can_be_repeated(tmp_path: Path) -> None:
    root = _legacy(tmp_path)
    source = (root / "data" / "tasks.db").read_bytes()
    database = Database(tmp_path / "maria.db")
    database.migrate()
    plan = scan(root, now=_NOW)
    first = apply(database, plan, now=_NOW)
    assert first.inserted > 0
    assert first.already == 0
    _expect_imported(database)
    second = apply(database, plan, now=_NOW)
    assert second.inserted == 0
    assert second.already == first.inserted
    assert (root / "data" / "tasks.db").read_bytes() == source
    database.close()


def test_the_command_prints_the_report_before_writing(tmp_path: Path, capsys) -> None:
    root = _legacy(tmp_path)
    destination = tmp_path / "maria.db"
    assert main([str(root), "--database", str(destination), "--now", _NOW.isoformat()]) == 0
    output = capsys.readouterr().out
    assert "Objectifs prêts" in output
    assert output.endswith("Aucune écriture.\n")
    assert not destination.exists()
    assert (
        main([str(root), "--database", str(destination), "--write", "--now", _NOW.isoformat()]) == 0
    )
    assert "Écrit :" in capsys.readouterr().out
    assert destination.is_file()


def test_a_missing_copy_is_reported(tmp_path: Path) -> None:
    text = render(scan(tmp_path / "absent", now=_NOW))
    assert "introuvable" in text


def _expect_imported(database: Database) -> None:
    kinds = {
        row["legacy_id"]: json.loads(row["trigger_json"])["type"]
        for row in database.fetchall(
            """
            SELECT legacy_id, trigger_json FROM legacy_map
            JOIN objectives ON objectives.id = legacy_map.row_id
            WHERE source = 'task'
            """
        )
    }
    assert kinds == {
        "1": "at",
        "2": "daily",
        "3": "weekly",
        "4": "interval",
        "5": "at",
        "6": "on_voice",
        "7": "on_topic",
        "10": "at",
        "11": "at",
        "12": "interval",
    }
    voice = database.fetchone(
        """
        SELECT trigger_json FROM objectives
        JOIN legacy_map ON legacy_map.row_id = objectives.id
        WHERE legacy_map.source = 'task' AND legacy_map.legacy_id = '6'
        """
    )
    assert voice is not None
    assert json.loads(voice["trigger_json"])["user_id"] == 7
    relative = database.fetchone(
        """
        SELECT condition_json FROM objectives
        JOIN legacy_map ON legacy_map.row_id = objectives.id
        WHERE legacy_map.source = 'task' AND legacy_map.legacy_id = '12'
        """
    )
    assert relative is not None
    assert json.loads(relative["condition_json"])["type"] == "price_lower"
    watch = database.fetchone(
        """
        SELECT action_json, condition_json, state_json FROM objectives
        JOIN legacy_map ON legacy_map.row_id = objectives.id
        WHERE legacy_map.source = 'task' AND legacy_map.legacy_id = '4'
        """
    )
    assert watch is not None
    assert json.loads(watch["action_json"])["type"] == "fetch_then"
    assert json.loads(watch["condition_json"]) == {"type": "price_below", "threshold": 20.0}
    assert json.loads(watch["state_json"])["price"] == 19.5
    memory = database.fetchone(
        "SELECT content, source, chroma_id FROM memories WHERE content = ?", ("joue du piano",)
    )
    assert memory is not None
    assert memory["source"] == "imported"
    assert memory["chroma_id"] == "chroma-piano"
    revision = database.fetchone("SELECT reason FROM memory_revisions")
    assert revision is not None
    assert revision["reason"] == "importé"
    proposal = database.fetchone("SELECT status FROM memory_proposals")
    assert proposal is not None
    assert proposal["status"] == "open"
    guild = database.fetchone("SELECT mode FROM guild_settings WHERE guild_id = 5")
    assert guild is not None
    assert guild["mode"] == "greedy"
    channel = database.fetchone(
        "SELECT respond_everyone FROM channel_settings WHERE channel_id = 9"
    )
    assert channel is not None
    assert channel["respond_everyone"] == 1
    emojis = {row["emoji"] for row in database.fetchall("SELECT emoji FROM emoji_usage")}
    assert emojis == {"😂", "<:maria:99>"}
    assert database.fetchone("SELECT question FROM polls")["question"] == "Ce soir ?"


def _legacy(tmp_path: Path) -> Path:
    root = tmp_path / "MARIA_R"
    data = root / "data"
    data.mkdir(parents=True)
    _tasks(data / "tasks.db")
    _memories(data / "memories.db")
    _emojis(data / "emoji_usage.db")
    _polls(data / "polls.db")
    _retired(data)
    _settings(root / "cogs" / "chat" / "data")
    return root


def _tasks(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY, channel_id INTEGER, user_id INTEGER, guild_id INTEGER,
            title TEXT, instruction TEXT, execute_at TEXT, schedule_kind TEXT, weekdays TEXT,
            time_of_day TEXT, status TEXT, deliver_dm INTEGER, kind TEXT, trigger_json TEXT,
            recipe_json TEXT, channel_ids TEXT, cooldown_seconds INTEGER, max_fires INTEGER,
            fires_count INTEGER, expires_at TEXT, created_at TEXT
        );
        CREATE TABLE member_vars (
            guild_id INTEGER, user_id INTEGER, key TEXT, value_json TEXT, ttl_expires_at TEXT
        );
        CREATE TABLE task_runs (id INTEGER PRIMARY KEY, task_id INTEGER, ran_at TEXT, summary TEXT);
        """
    )
    rows = [
        (
            1,
            "Appelle Lina",
            "at",
            "once",
            "pending",
            "{}",
            "{}",
            "2026-12-01T10:00:00+00:00",
            "",
            "[]",
            "2026-10-01T10:00:00+00:00",
        ),
        (
            2,
            "Bilan",
            "recurring",
            "daily",
            "pending",
            "{}",
            "{}",
            "2026-10-11T18:00:00+00:00",
            "21:30",
            "[]",
            "2026-10-01T10:00:00+00:00",
        ),
        (
            3,
            "Hebdo",
            "recurring",
            "weekly",
            "pending",
            "{}",
            "{}",
            "2026-10-11T18:00:00+00:00",
            "09:00",
            '["mon"]',
            "2026-10-01T10:00:00+00:00",
        ),
        (
            4,
            "Prix",
            "watch",
            "once",
            "pending",
            _watch("lt"),
            '{"say":"Le prix a baissé."}',
            "2026-10-11T18:00:00+00:00",
            "",
            "[]",
            "2026-10-01T10:00:00+00:00",
        ),
        (
            5,
            "Cherche",
            "at",
            "once",
            "pending",
            "{}",
            _search(),
            "2026-12-01T10:00:00+00:00",
            "",
            "[]",
            "2026-10-01T10:00:00+00:00",
        ),
        (
            6,
            "Vocal",
            "event",
            "once",
            "armed",
            _voice(),
            "{}",
            "2026-10-11T18:00:00+00:00",
            "",
            "[]",
            "2026-10-01T10:00:00+00:00",
        ),
        (
            7,
            "Ranked",
            "event",
            "once",
            "armed",
            '{"pattern":"ranked","author":"not_self"}',
            "{}",
            "2026-10-11T18:00:00+00:00",
            "",
            "[]",
            "2026-10-01T10:00:00+00:00",
        ),
        (
            8,
            "Fini",
            "at",
            "once",
            "completed",
            "{}",
            "{}",
            "2026-09-01T10:00:00+00:00",
            "",
            "[]",
            "2026-09-01T10:00:00+00:00",
        ),
        (
            9,
            "Vieux brouillon",
            "at",
            "once",
            "draft",
            "{}",
            "{}",
            "2026-12-01T10:00:00+00:00",
            "",
            "[]",
            "2026-10-11T17:00:00+00:00",
        ),
        (
            10,
            "Brouillon",
            "at",
            "once",
            "draft",
            "{}",
            "{}",
            "2026-12-01T10:00:00+00:00",
            "",
            "[]",
            "2026-10-11T17:55:00+00:00",
        ),
        (
            11,
            "En cours",
            "at",
            "once",
            "running",
            "{}",
            "{}",
            "2026-12-01T10:00:00+00:00",
            "",
            "[]",
            "2026-10-01T10:00:00+00:00",
        ),
        (
            12,
            "Relatif",
            "watch",
            "once",
            "pending",
            _watch("lt_prev", "relatif"),
            "{}",
            "2026-10-11T18:00:00+00:00",
            "",
            "[]",
            "2026-10-01T10:00:00+00:00",
        ),
    ]
    connection.executemany(
        """
        INSERT INTO tasks (
            id, channel_id, user_id, guild_id, title, instruction, kind, schedule_kind, status,
            trigger_json, recipe_json, execute_at, time_of_day, weekdays, created_at, channel_ids
        ) VALUES (?, 9, 7, 5, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]')
        """,
        rows,
    )
    connection.execute(
        """
        INSERT INTO member_vars (guild_id, user_id, key, value_json)
        VALUES (5, 7, 'prix', '19.50')
        """
    )
    connection.execute(
        "INSERT INTO task_runs (task_id, ran_at, summary) VALUES (8, '2026-09-01', 'ok')"
    )
    connection.commit()
    connection.close()


def _watch(op: str, var_key: str = "prix") -> str:
    return json.dumps(
        {
            "url": "https://example.test/p",
            "op": op,
            "threshold": 20,
            "interval_minutes": 360,
            "var_key": var_key,
        }
    )


def _search() -> str:
    return json.dumps({"plan": {"primary": {"type": "web_search", "query": "maria"}}})


def _voice() -> str:
    return json.dumps(
        {"type": "discord", "signal": "voice_join", "user_id": "7", "pattern": "voice_join:7:0"}
    )


def _memories(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, category TEXT, guild_id INTEGER, user_id INTEGER,
            content TEXT, created_at TEXT, confirmed_at TEXT, confidence REAL,
            status TEXT, chroma_id TEXT
        )
        """
    )
    rows = [
        ("u1", "user", 5, 7, "joue du piano", "active", "chroma-piano"),
        ("s1", "server", 5, 7, "le salon annonces est calme", "active", ""),
        ("m1", "self", 5, 7, "préfère les réponses courtes", "active", "chroma-self"),
        ("m2", "self", 5, 7, "préfère les réponses courtes", "active", "chroma-self-2"),
        ("p1", "user", 5, 7, "habite à Lyon", "pending", ""),
        ("a1", "user", 5, 7, "ancien", "archived", ""),
        ("e1", "event", 5, 7, "soirée", "active", ""),
    ]
    connection.executemany(
        """
        INSERT INTO memories (
            id, category, guild_id, user_id, content, created_at, confirmed_at,
            confidence, status, chroma_id
        ) VALUES (
            ?, ?, ?, ?, ?, '2026-10-01T10:00:00+00:00', '2026-10-01T10:00:00+00:00', 0.9, ?, ?
        )
        """,
        rows,
    )
    connection.commit()
    connection.close()


def _emojis(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE emoji_stats (
            guild_id INTEGER, emoji_id INTEGER, emoji_name TEXT, animated INTEGER,
            count INTEGER, last_seen REAL
        )
        """
    )
    connection.executemany(
        "INSERT INTO emoji_stats VALUES (?, ?, ?, ?, ?, ?)",
        [(5, -1, "😂", 0, 4, 1_760_000_000.0), (5, 99, "maria", 0, 2, 1_760_000_000.0)],
    )
    connection.commit()
    connection.close()


def _polls(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE polls (
            message_id INTEGER PRIMARY KEY, channel_id INTEGER, guild_id INTEGER,
            author_id INTEGER, question TEXT, options TEXT, created_at TEXT, expires_at TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO polls VALUES (100, 9, 5, 7, 'Ce soir ?', ?, ?, ?)",
        ('["oui", "non"]', "2026-10-11T18:00:00+00:00", "2026-10-11T20:00:00+00:00"),
    )
    connection.commit()
    connection.close()


def _retired(data: Path) -> None:
    for name, table in (
        ("funstat.db", "campaigns"),
        ("bookmarks.db", "bookmarks"),
        ("activity.db", "activity"),
    ):
        connection = sqlite3.connect(data / name)
        connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        connection.execute(f"INSERT INTO {table} (id) VALUES (1)")
        connection.commit()
        connection.close()


def _settings(folder: Path) -> None:
    folder.mkdir(parents=True)
    _kv(folder / "guild_5.db", "guild_config", {"chatbot_mode": "greedy", "theme": "nuit"})
    _kv(
        folder / "textchannel_9.db",
        "channel_config",
        {"respond_everyone": "1", "auto_transcribe": "0"},
    )
    _kv(
        folder / "textchannel_8.db",
        "channel_config",
        {"respond_everyone": "0", "auto_transcribe": "0"},
    )


def _kv(path: Path, table: str, pairs: dict[str, str]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(f"CREATE TABLE {table} (key TEXT PRIMARY KEY, value TEXT)")
    connection.executemany(f"INSERT INTO {table} VALUES (?, ?)", list(pairs.items()))
    connection.commit()
    connection.close()


def test_imported_reminders_become_reports_so_the_instruction_runs(tmp_path: Path) -> None:
    older = tmp_path / "migrations"
    older.mkdir()
    for path in sorted(DEFAULT_MIGRATIONS.glob("*.sql")):
        if path.name < "012":
            shutil.copy(path, older / path.name)
    database = Database(tmp_path / "maria.db", migrations_dir=older)
    database.migrate()
    store = ObjectiveStore(database)
    moment = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    rows = [
        store.create(
            owner_id=7,
            guild_id=5,
            channel_ids=(3,),
            deliver="channel",
            title=f"Décompte {index}",
            trigger={"type": "daily", "time": f"1{index}:00"},
            condition=None,
            action={"type": "remind", "text": "Donne le nombre de jours avant Halloween."},
            now=moment,
        )[0]
        for index in range(2)
    ]
    database.execute("INSERT INTO legacy_map VALUES ('task', '42', 'objectives', ?)", (rows[0].id,))
    database.close()
    upgraded = Database(tmp_path / "maria.db")
    upgraded.migrate()
    kinds = [ObjectiveStore(upgraded).get(row.id).action["type"] for row in rows]
    assert kinds == ["report", "remind"]
    upgraded.close()
