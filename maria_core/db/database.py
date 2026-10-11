"""SQLite unique, migrations numérotées, sauvegarde avant chaque changement de schéma."""

import logging
import re
import shutil
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from maria_core.errors import DatabaseError, MigrationError

logger = logging.getLogger(__name__)

DEFAULT_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_FILENAME = re.compile(r"^(\d{3,})_([a-z0-9_]+)\.sql$")
_BOOKKEEPING = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path


@dataclass(frozen=True, slots=True)
class WriteResult:
    rowcount: int
    lastrowid: int


class Database:
    """Connexion unique. Les écritures groupées passent par `transaction`."""

    def __init__(self, path: Path, *, migrations_dir: Path | None = None) -> None:
        self._path = path
        self._migrations_dir = migrations_dir or DEFAULT_MIGRATIONS
        self._backup_dir = path.parent / "backups"
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._txn = False
        self._migrations = _load_migrations(self._migrations_dir)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connect()

    def migrate(self) -> tuple[str, ...]:
        """Applique les fichiers manquants. Échec : retour au fichier sauvegardé."""
        with self._lock:
            self._ensure_open()
            if self._txn:
                raise DatabaseError("Impossible de migrer pendant une transaction.")
            self._reconcile_version()
            applied: list[str] = []
            for migration in self._pending():
                self._apply(migration)
                applied.append(migration.name)
            if not applied:
                logger.debug("Schéma à jour (v%s)", self._version())
            return tuple(applied)

    @property
    def version(self) -> int:
        with self._lock:
            self._ensure_open()
            return self._version()

    def fetchall(self, sql: str, params: Sequence[object] = ()) -> list[sqlite3.Row]:
        with self._lock:
            self._ensure_open()
            try:
                rows = list(self._connection().execute(sql, params).fetchall())
            except sqlite3.Error:
                self._abort_statement()
                raise
            self._finish_implicit()
            return rows

    def fetchone(self, sql: str, params: Sequence[object] = ()) -> sqlite3.Row | None:
        with self._lock:
            self._ensure_open()
            try:
                row = self._connection().execute(sql, params).fetchone()
            except sqlite3.Error:
                self._abort_statement()
                raise
            self._finish_implicit()
            return row

    def execute(self, sql: str, params: Sequence[object] = ()) -> WriteResult:
        with self._lock:
            self._ensure_open()
            try:
                cursor = self._connection().execute(sql, params)
                result = WriteResult(cursor.rowcount, int(cursor.lastrowid or 0))
            except sqlite3.Error:
                self._abort_statement()
                raise
            self._finish_implicit()
            return result

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Groupe des écritures. Pas d'imbrication, et aucun `await` dans le bloc."""
        with self._lock:
            self._ensure_open()
            if self._txn:
                raise DatabaseError("Transaction imbriquée non supportée.")
            connection = self._connection()
            connection.execute("BEGIN IMMEDIATE")
            self._txn = True
            try:
                yield
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                self._txn = False

    def close(self) -> None:
        with self._lock:
            self._close()

    def _apply(self, migration: Migration) -> None:
        backup = self._backup() if self._version() > 0 else None
        connection = self._connection()
        try:
            script = migration.path.read_text(encoding="utf-8")
            connection.executescript(script)
            connection.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, _now()),
            )
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.commit()
        except (sqlite3.Error, OSError) as exc:
            self._recover(backup)
            raise MigrationError(f"Migration {migration.name} échouée : {exc}") from exc
        logger.info("Migration appliquée : %s (v%s)", migration.name, migration.version)

    def _recover(self, backup: Path | None) -> None:
        try:
            self._connection().rollback()
        except sqlite3.Error:
            logger.debug("Rien à annuler après l'échec de migration", exc_info=True)
        self._close()
        _remove_sqlite_files(self._path)
        if backup is not None:
            shutil.copy2(backup, self._path)
        self._connect()

    def _backup(self) -> Path:
        self._connection().execute("PRAGMA wal_checkpoint(FULL)").fetchall()
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = self._backup_dir / f"maria-v{self._version()}-{stamp}.db"
        shutil.copy2(self._path, destination)
        logger.info("Sauvegarde avant migration : %s", destination.name)
        return destination

    def _pending(self) -> tuple[Migration, ...]:
        current = self._version()
        return tuple(item for item in self._migrations if item.version > current)

    def _reconcile_version(self) -> None:
        row = self._connection().execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        recorded = int(row[0] or 0) if row is not None else 0
        header = self._version()
        if header == recorded:
            return
        if header < recorded:
            self._connection().execute(f"PRAGMA user_version = {recorded}")
            logger.warning("user_version rétabli à %s d'après schema_migrations", recorded)
            return
        raise MigrationError(
            f"user_version={header} est en avance sur schema_migrations={recorded}."
        )

    def _version(self) -> int:
        row = self._connection().execute("PRAGMA user_version").fetchone()
        if row is None:
            return 0
        return int(row[0])

    def _finish_implicit(self) -> None:
        if self._txn or self._conn is None:
            return
        self._conn.commit()

    def _abort_statement(self) -> None:
        if self._txn or self._conn is None:
            return
        self._conn.rollback()

    def _connect(self) -> None:
        connection = sqlite3.connect(self._path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute(_BOOKKEEPING)
        connection.commit()
        self._conn = connection

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise DatabaseError("La base est fermée.")
        return self._conn

    def _ensure_open(self) -> None:
        if self._conn is None:
            raise DatabaseError("La base est fermée.")

    def _close(self) -> None:
        if self._conn is None:
            return
        self._conn.close()
        self._conn = None


def _load_migrations(directory: Path) -> tuple[Migration, ...]:
    if not directory.is_dir():
        raise MigrationError(f"Dossier de migrations introuvable : {directory}")
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"Nom de migration invalide : {path.name}")
        found.append(Migration(int(match.group(1)), path.stem, path))
    if not found:
        raise MigrationError(f"Aucune migration dans {directory}.")
    versions = [item.version for item in found]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(f"Migrations non contiguës : {versions or 'aucune'}.")
    return tuple(found)


def _remove_sqlite_files(path: Path) -> None:
    path.unlink(missing_ok=True)
    Path(f"{path}-wal").unlink(missing_ok=True)
    Path(f"{path}-shm").unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(UTC).isoformat()
