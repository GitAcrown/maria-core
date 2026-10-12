"""Retour arrière : liste en JSON les objectifs et souvenirs créés depuis la bascule.

`python scripts/export_since_cutover.py data/maria.db 2026-10-20T08:00:00+00:00 > depuis.json`
La base est ouverte en lecture seule.
"""

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="export_since_cutover")
    parser.add_argument("database", type=Path)
    parser.add_argument("since", help="Instant ISO de la bascule")
    args = parser.parse_args(argv)
    try:
        since = datetime.fromisoformat(args.since)
    except ValueError:
        print("Date illisible.", file=sys.stderr)
        return 2
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    if not args.database.is_file():
        print(f"Base introuvable : {args.database}", file=sys.stderr)
        return 2
    connection = sqlite3.connect(f"file:{args.database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        payload = {
            "since": since.astimezone(UTC).isoformat(),
            "objectives": _rows(
                connection,
                """
                SELECT id, owner_id, guild_id, title, status, trigger_json, condition_json,
                       action_json, created_at
                FROM objectives WHERE created_at >= ? ORDER BY id
                """,
                since,
            ),
            "memories": _rows(
                connection,
                """
                SELECT id, scope, subject_id, guild_id, content, source, created_at, deleted_at
                FROM memories WHERE created_at >= ? ORDER BY id
                """,
                since,
            ),
        }
    finally:
        connection.close()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _rows(connection: sqlite3.Connection, sql: str, since: datetime) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute(sql, (since.astimezone(UTC).isoformat(),))]


if __name__ == "__main__":
    raise SystemExit(main())
