"""Index vectoriel. La recherche texte reste dans SQLite ; ici, le voisinage sémantique."""

from typing import Protocol


class VectorIndex(Protocol):
    def upsert(self, memory_id: int, text: str) -> None: ...

    def delete(self, memory_id: int) -> None: ...

    def search(self, text: str, *, limit: int) -> tuple[int, ...]: ...
