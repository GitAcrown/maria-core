"""`python -m maria_core.legacy <copie> --database <base>`."""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from maria_core.db import Database
from maria_core.legacy.apply import apply
from maria_core.legacy.chroma_link import adopt
from maria_core.legacy.report import render
from maria_core.legacy.scan import scan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="import_legacy")
    parser.add_argument("root", type=Path, help="Copie du dossier MARIA_R")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--write", action="store_true", help="Écrit les lignes convertibles")
    parser.add_argument("--now", default="", help="Instant ISO utilisé pour les brouillons")
    args = parser.parse_args(argv)
    now = _now(args.now)
    if now is None:
        print("Date --now illisible.", file=sys.stderr)
        return 2
    print(render(scan(args.root, now=now)))
    if not args.write:
        print("Aucune écriture.")
        return 0
    database = Database(args.database)
    try:
        database.migrate()
        print(apply(database, scan(args.root, now=now), now=now).text())
        print(adopt(args.root / "data" / "chroma", args.database.parent / "chroma", database))
    finally:
        database.close()
    return 0


def _now(raw: str) -> datetime | None:
    if not raw.strip():
        return datetime.now(UTC)
    try:
        value = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
