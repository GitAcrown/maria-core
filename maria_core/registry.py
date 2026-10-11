"""Registre nommé. Le déchargement d'une extension retire ce qu'elle a ajouté."""

from maria_core.errors import RegistryError
from maria_core.ledger import note_undo
from maria_core.names import require_name


class Registry[T]:
    def __init__(self, *, kind: str) -> None:
        self._kind = kind
        self._items: dict[str, T] = {}

    def add(self, name: str, item: T) -> None:
        require_name(name, what=self._kind)
        if name in self._items:
            raise RegistryError(f"{self._kind} déjà enregistré : {name}")
        self._items[name] = item
        note_undo(lambda key=name: self._items.pop(key, None))

    def get(self, name: str) -> T:
        try:
            return self._items[name]
        except KeyError as exc:
            raise RegistryError(f"{self._kind} inconnu : {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(self._items)

    def values(self) -> tuple[T, ...]:
        return tuple(self._items.values())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._items

    def __len__(self) -> int:
        return len(self._items)
