"""Accès à la base. Le métier importe `Database`, pas sqlite3 de partout."""

from maria_core.db.database import DEFAULT_MIGRATIONS, Database, WriteResult

__all__ = ["DEFAULT_MIGRATIONS", "Database", "WriteResult"]
