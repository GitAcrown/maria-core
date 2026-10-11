"""Index vide. La recherche hybride retombe sur FTS5 tant qu'aucun moteur n'est branché."""


class NullIndex:
    def upsert(self, memory_id: int, text: str) -> None:
        return None

    def delete(self, memory_id: int) -> None:
        return None

    def search(self, text: str, *, limit: int) -> tuple[int, ...]:
        return ()
