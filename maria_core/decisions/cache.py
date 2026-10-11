"""Cache mémoire des réponses du modèle. Les règles n'y passent pas."""

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any


@dataclass(frozen=True, slots=True)
class _Entry:
    value: Any
    confidence: float
    expires: float


class MemoryCache:
    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or monotonic
        self._items: dict[str, _Entry] = {}

    def get(self, key: str) -> tuple[Any, float] | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires <= self._clock():
            self._items.pop(key, None)
            return None
        return entry.value, entry.confidence

    def put(self, key: str, value: Any, confidence: float, ttl: float) -> None:
        if ttl <= 0:
            return
        self._items[key] = _Entry(value, confidence, self._clock() + ttl)
