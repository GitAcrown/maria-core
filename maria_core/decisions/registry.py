"""Catalogue des décisions. L'exécution (cache, budget, backend) viendra ensuite."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from maria_core.decisions.types import Question
from maria_core.errors import RegistryError
from maria_core.names import require_name
from maria_core.registry import Registry

_BACKENDS = frozenset({"structured", "llm"})


@dataclass(frozen=True, slots=True)
class Decision:
    """Une question nommée : règles d'abord, modèle ensuite, repli toujours défini."""

    name: str
    threshold: float
    fallback: Any
    rules: Callable[[Mapping[str, Any]], Any] | None = None
    backend: Literal["structured", "llm"] = "structured"
    cache_ttl_s: float = 0
    budget_per_day: int | None = None
    question: Question | None = None

    def __post_init__(self) -> None:
        require_name(self.name, what="Décision")
        if not isinstance(self.threshold, (int, float)) or isinstance(self.threshold, bool):
            raise RegistryError("Le seuil d'une décision doit être un nombre.")
        if not 0 <= float(self.threshold) <= 1:
            raise RegistryError("Le seuil d'une décision doit être compris entre 0 et 1.")
        if self.backend not in _BACKENDS:
            raise RegistryError(f"Backend de décision inconnu : {self.backend!r}.")
        if self.cache_ttl_s < 0:
            raise RegistryError("cache_ttl_s doit être positif ou nul.")
        if self.rules is not None and not callable(self.rules):
            raise RegistryError("rules doit être appelable.")
        if self.budget_per_day is not None and self.budget_per_day < 0:
            raise RegistryError("budget_per_day doit être positif ou nul.")


class DecisionRegistry:
    def __init__(self) -> None:
        self._items: Registry[Decision] = Registry(kind="Décision")

    def register(self, decision: Decision) -> None:
        if not isinstance(decision, Decision):
            raise RegistryError("Décision attendue.")
        self._items.add(decision.name, decision)

    def get(self, name: str) -> Decision:
        return self._items.get(name)

    def names(self) -> tuple[str, ...]:
        return self._items.names()

    def __contains__(self, name: object) -> bool:
        return name in self._items
