"""L'index aligne un vecteur importé sur l'identifiant du souvenir."""

from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction

from maria_core.db import Database
from maria_core.legacy.chroma_link import adopt, realign
from maria_core.vectors.chroma import ChromaIndex, open_index

_STAMP = "2026-10-01T00:00:00+00:00"


def test_a_missing_chroma_library_stays_quiet(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("maria_core.vectors.chroma.chromadb", None)
    assert open_index(tmp_path / "chroma", "sk-test") is None
    assert not (tmp_path / "chroma").exists()


def test_without_a_key_no_index_is_opened(tmp_path: Path) -> None:
    assert open_index(tmp_path / "chroma", "") is None
    assert not (tmp_path / "chroma").exists()


def test_a_legacy_vector_follows_the_new_memory_id(tmp_path: Path) -> None:
    database = _database(tmp_path)
    shelf = _Shelf()
    shelf.rows["abc"] = {"document": "joue du piano", "embedding": [0.2, 0.4]}
    index = ChromaIndex(shelf)
    assert realign(index, database) == (1, 0)
    assert "abc" not in shelf.rows
    assert shelf.rows["1"]["embedding"] == [0.2, 0.4]
    stored = database.fetchone("SELECT chroma_id FROM memories WHERE id = 1")
    assert stored is not None
    assert stored["chroma_id"] == "1"
    assert index.search("piano", limit=2) == (1,)
    assert realign(index, database) == (0, 0)
    database.close()


def test_a_missing_vector_is_left_in_place(tmp_path: Path) -> None:
    database = _database(tmp_path)
    assert realign(ChromaIndex(_Shelf()), database) == (0, 1)
    stored = database.fetchone("SELECT chroma_id FROM memories WHERE id = 1")
    assert stored is not None
    assert stored["chroma_id"] == "abc"
    database.close()


def test_the_real_client_moves_a_vector_without_calling_the_model() -> None:
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection("maria_memories", embedding_function=_Hash())
    collection.upsert(ids=["abc"], documents=["joue du piano"], metadatas=[{"memory_id": 0}])
    index = ChromaIndex(collection)
    assert index.move("abc", 4) is True
    assert index.search("piano", limit=2) == (4,)
    assert collection.get(include=[])["ids"] == ["4"]


def test_adopt_copies_the_folder_without_touching_the_source(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "keep.txt").write_text("intact", encoding="utf-8")
    destination = tmp_path / "data" / "chroma"
    monkeypatch.setattr("maria_core.legacy.chroma_link.open_stored", lambda _path: None)
    database = Database(tmp_path / "maria.db")
    database.migrate()
    assert adopt(source, destination, database) == "Index Chroma illisible."
    assert (destination / "keep.txt").read_text(encoding="utf-8") == "intact"
    assert (source / "keep.txt").read_text(encoding="utf-8") == "intact"
    database.close()


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "maria.db")
    database.migrate()
    database.execute(
        """
        INSERT INTO memories (
            scope, subject_id, guild_id, content, source, created_by,
            created_at, updated_at, chroma_id
        ) VALUES ('user', 7, 5, 'joue du piano', 'imported', 7, ?, ?, 'abc')
        """,
        (_STAMP, _STAMP),
    )
    return database


class _Hash(EmbeddingFunction[Documents]):
    def __init__(self) -> None:
        return None

    def __call__(self, documents: Documents) -> list[list[float]]:
        return [[float(len(text)), 1.0] for text in documents]

    @staticmethod
    def name() -> str:
        return "hash"

    def get_config(self) -> dict[str, str]:
        return {}

    @staticmethod
    def build_from_config(_config: dict[str, str]) -> _Hash:
        return _Hash()


class _Shelf:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}

    def upsert(
        self,
        *,
        ids: list[str],
        documents: list[str] | None = None,
        embeddings: list[list[float]] | None = None,
        metadatas: list[dict[str, int]] | None = None,
    ) -> None:
        for index, item_id in enumerate(ids):
            current = dict(self.rows.get(item_id, {}))
            if documents is not None:
                current["document"] = documents[index]
            if embeddings is not None:
                current["embedding"] = embeddings[index]
            if metadatas is not None:
                current["metadata"] = metadatas[index]
            self.rows[item_id] = current

    def delete(self, *, ids: list[str]) -> None:
        for item_id in ids:
            self.rows.pop(item_id, None)

    def query(self, *, query_texts: list[str], n_results: int) -> dict[str, object]:
        needle = query_texts[0].casefold()
        hits = [
            key
            for key, row in self.rows.items()
            if needle in str(row.get("document", "")).casefold()
        ]
        return {"ids": [hits[:n_results]]}

    def get(self, *, ids: list[str], include: list[str]) -> dict[str, object]:
        found = [item_id for item_id in ids if item_id in self.rows]
        return {
            "ids": found,
            "embeddings": [self.rows[item_id]["embedding"] for item_id in found],
            "documents": [self.rows[item_id]["document"] for item_id in found],
            "include": include,
        }
