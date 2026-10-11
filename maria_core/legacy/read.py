"""Ouverture des bases MARIA_R. Jamais d'écriture."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_QUOTED = str.maketrans({'"': ""})


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def load(path: Path, table: str) -> list[sqlite3.Row] | None:
    """`None` si le fichier n'existe pas. Liste vide si la table n'existe pas."""
    if not path.is_file():
        return None
    connection = connect(path)
    try:
        names = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master")}
        if table not in names:
            return []
        return list(connection.execute(f"SELECT * FROM {table}"))
    finally:
        connection.close()


def count_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    connection = connect(path)
    try:
        total = 0
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
            name = str(row[0]).translate(_QUOTED)
            if name.startswith("sqlite_"):
                continue
            total += int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
        return total
    finally:
        connection.close()


def cell(row: sqlite3.Row, key: str, default: object = "") -> object:
    try:
        value = row[key]
    except IndexError:
        return default
    return default if value is None else value


def as_dict(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def moment(raw: object) -> datetime | None:
    if isinstance(raw, datetime):
        value = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            value = datetime.fromisoformat(raw.strip())
        except ValueError:
            return None
    else:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def positive(raw: object) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int | str):
        return None
    try:
        number = int(raw)
    except ValueError:
        return None
    return number if number > 0 else None
