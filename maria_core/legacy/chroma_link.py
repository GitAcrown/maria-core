"""Recopie l'index Chroma de MARIA_R, puis aligne chaque vecteur sur le nouveau souvenir."""

import shutil
from pathlib import Path

from maria_core.db import Database
from maria_core.vectors.chroma import ChromaIndex, open_stored


def adopt(source: Path, destination: Path, database: Database) -> str:
    if not source.is_dir():
        return "Pas d'index Chroma dans la source."
    if not destination.exists():
        shutil.copytree(source, destination)
    index = open_stored(destination)
    if index is None:
        return "Index Chroma illisible."
    moved, missing = realign(index, database)
    return f"Index Chroma : {moved} réalignés, {missing} introuvables."


def realign(index: ChromaIndex, database: Database) -> tuple[int, int]:
    moved = missing = 0
    rows = database.fetchall(
        """
        SELECT id, chroma_id FROM memories
        WHERE deleted_at IS NULL AND chroma_id IS NOT NULL
        """
    )
    for row in rows:
        memory_id = int(row["id"])
        old = str(row["chroma_id"])
        if old == str(memory_id):
            continue
        if not index.move(old, memory_id):
            missing += 1
            continue
        database.execute(
            "UPDATE memories SET chroma_id = ? WHERE id = ?",
            (str(memory_id), memory_id),
        )
        moved += 1
    return moved, missing
