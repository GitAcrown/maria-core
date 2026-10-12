"""`python -m maria_core.legacy <copie> --database <base>`."""

import argparse
import shutil
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
        print(_statuses(args.root / "data" / "statuses.txt", args.database.parent))
    finally:
        database.close()
    return 0


def _statuses(source: Path, folder: Path) -> str:
    """Les statuts tournants de MARIA_R, recopiés s'il n'y en a pas déjà."""
    target = folder / "statuses.txt"
    if not source.is_file():
        return "Pas de statuts à reprendre."
    if target.exists():
        return "Statuts déjà présents, conservés."
    shutil.copyfile(source, target)
    return "Statuts repris."


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


if __name__ == "__main__":
    sys.exit(main())
