"""Index Chroma local. L'identifiant d'un vecteur est celui du souvenir SQLite."""

import logging
from pathlib import Path
from typing import Protocol

try:
    import chromadb
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
except ImportError:
    chromadb = None
    OpenAIEmbeddingFunction = None

logger = logging.getLogger(__name__)

_COLLECTION = "maria_memories"
_MODEL = "text-embedding-3-small"
_MARKER = "chroma.sqlite3"


class _Collection(Protocol):
    def upsert(
        self,
        *,
        ids: list[str],
        documents: list[str] | None = None,
        embeddings: list[list[float]] | None = None,
        metadatas: list[dict[str, int]] | None = None,
    ) -> None: ...

    def delete(self, *, ids: list[str]) -> None: ...

    def query(self, *, query_texts: list[str], n_results: int) -> dict[str, object]: ...

    def get(self, *, ids: list[str], include: list[str]) -> dict[str, object]: ...


class ChromaIndex:
    def __init__(self, collection: _Collection) -> None:
        self._collection = collection

    def upsert(self, memory_id: int, text: str) -> None:
        try:
            self._collection.upsert(
                ids=[str(memory_id)],
                documents=[text],
                metadatas=[{"memory_id": memory_id}],
            )
        except Exception:
            logger.warning("Index : écriture ignorée pour %s", memory_id, exc_info=True)

    def delete(self, memory_id: int) -> None:
        try:
            self._collection.delete(ids=[str(memory_id)])
        except Exception:
            logger.warning("Index : suppression ignorée pour %s", memory_id, exc_info=True)

    def search(
        self, text: str, *, limit: int, max_distance: float | None = None
    ) -> tuple[int, ...]:
        """Les plus proches voisins ; au-delà de `max_distance` (cosinus), rien n'est rendu."""
        cleaned = text.strip()
        if not cleaned or limit < 1:
            return ()
        try:
            found = self._collection.query(query_texts=[cleaned[:2000]], n_results=limit)
        except Exception:
            logger.warning("Index : recherche ignorée", exc_info=True)
            return ()
        if max_distance is None:
            return _identifiers(found)
        return _close(found, max_distance)

    def move(self, old_id: str, memory_id: int) -> bool:
        target = str(memory_id)
        if old_id == target:
            return True
        stored = self._read(old_id)
        if stored is None:
            return False
        embedding, document = stored
        try:
            self._collection.upsert(
                ids=[target],
                embeddings=[embedding],
                documents=[document],
                metadatas=[{"memory_id": memory_id}],
            )
            self._collection.delete(ids=[old_id])
        except Exception:
            logger.warning("Index : déplacement ignoré pour %s", old_id, exc_info=True)
            return False
        return True

    def _read(self, old_id: str) -> tuple[list[float], str] | None:
        try:
            payload = self._collection.get(
                ids=[old_id],
                include=["embeddings", "documents"],
            )
        except Exception:
            logger.warning("Index : lecture ignorée pour %s", old_id, exc_info=True)
            return None
        embedding = _vector(payload)
        document = _text(payload)
        if embedding is None or document is None:
            return None
        return embedding, document


def open_index(path: Path, api_key: str) -> ChromaIndex | None:
    if chromadb is None or OpenAIEmbeddingFunction is None or not api_key.strip():
        return None
    try:
        path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(path))
        function = OpenAIEmbeddingFunction(api_key=api_key.strip(), model_name=_MODEL)
        collection = client.get_or_create_collection(
            name=_COLLECTION,
            embedding_function=function,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception:
        logger.warning("Index vectoriel indisponible", exc_info=True)
        return None
    return ChromaIndex(collection)


def open_stored(path: Path) -> ChromaIndex | None:
    if chromadb is None or not (path / _MARKER).is_file():
        return None
    try:
        client = chromadb.PersistentClient(path=str(path))
        collection = client.get_collection(_COLLECTION)
    except Exception:
        logger.warning("Index Chroma illisible : %s", path, exc_info=True)
        return None
    return ChromaIndex(collection)


def _identifiers(payload: object) -> tuple[int, ...]:
    rows = _field(payload, "ids")
    if rows and isinstance(rows[0], list):
        rows = rows[0]
    found: list[int] = []
    for item in rows:
        if isinstance(item, str) and item.isdigit():
            found.append(int(item))
    return tuple(found)


def _close(payload: object, max_distance: float) -> tuple[int, ...]:
    ids = _first(_field(payload, "ids"))
    distances = _first(_field(payload, "distances"))
    if len(distances) != len(ids):
        return _identifiers(payload)
    found: list[int] = []
    for raw, distance in zip(ids, distances, strict=True):
        if isinstance(raw, str) and raw.isdigit() and _number(distance) <= max_distance:
            found.append(int(raw))
    return tuple(found)


def _first(rows: list[object]) -> list[object]:
    if rows and isinstance(rows[0], list):
        return list(rows[0])
    return rows


def _number(raw: object) -> float:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("inf")


def _vector(payload: object) -> list[float] | None:
    rows = _field(payload, "embeddings")
    if not rows:
        return None
    raw = rows[0]
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    if not isinstance(raw, list) or not raw:
        return None
    try:
        return [float(item) for item in raw]
    except (TypeError, ValueError):
        return None


def _text(payload: object) -> str | None:
    rows = _field(payload, "documents")
    if not rows or not isinstance(rows[0], str) or not rows[0].strip():
        return None
    return rows[0]


def _field(payload: object, key: str) -> list[object]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get(key)
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    if not isinstance(raw, list):
        return []
    return raw
