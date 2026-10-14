"""Cache des résultats d'outils publics (météo, fiches, transports…), un seul endroit pour tous.

MARIA_R avait un cache par module. Ici une capacité déclare `cache_s` et le coureur s'en charge :
seuls les résultats réussis sont gardés, et la clé est le nom plus les arguments préparés.
"""

import json
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Any

from maria_core.capabilities.base import Result

_MAX_ITEMS = 256


class ResultCache:
    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._items: OrderedDict[str, tuple[float, Result]] = OrderedDict()

    def get(self, name: str, arguments: Mapping[str, Any]) -> Result | None:
        key = _key(name, arguments)
        found = self._items.get(key)
        if found is None:
            return None
        until, result = found
        if self._clock() >= until:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return result

    def put(self, name: str, arguments: Mapping[str, Any], result: Result, ttl: float) -> None:
        if ttl <= 0 or not result.ok:
            return
        self._items[_key(name, arguments)] = (self._clock() + ttl, result)
        self._items.move_to_end(_key(name, arguments))
        while len(self._items) > _MAX_ITEMS:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


def _key(name: str, arguments: Mapping[str, Any]) -> str:
    folded = {key: _fold(value) for key, value in arguments.items()}
    return f"{name}:{json.dumps(folded, sort_keys=True, ensure_ascii=False, default=str)}"


def _fold(value: Any) -> Any:
    return " ".join(value.casefold().split()) if isinstance(value, str) else value
