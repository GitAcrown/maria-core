"""Contrat d'une capacité. L'exécution commune arrivera avec le registre d'outils."""

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from maria_core.errors import RegistryError
from maria_core.names import require_name
from maria_core.registry import Registry

# Un argument vaut « @profil » : l'outil lit le champ correspondant du profil de la personne.
PROFILE_MARK = "@profil"


class Risk(StrEnum):
    READ = "read"
    WRITE = "write"
    EXTERNAL = "external"
    DANGEROUS = "dangerous"


@dataclass(frozen=True, slots=True)
class Source:
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class Context:
    user_id: int
    guild_id: int | None
    channel_id: int
    message_id: int | None
    is_owner: bool
    is_moderator: bool
    text: str
    author_name: str = ""

    def __post_init__(self) -> None:
        _positive(self.user_id, "user_id")
        _positive(self.channel_id, "channel_id")
        _optional_positive(self.guild_id, "guild_id")
        _optional_positive(self.message_id, "message_id")


@dataclass(frozen=True, slots=True)
class Result:
    ok: bool
    data: Mapping[str, Any]
    error: str = ""
    widget: str | None = None
    sources: tuple[Source, ...] = ()
    needs_confirmation: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))
        if self.widget is not None:
            require_name(self.widget, what="Widget")


type CapabilityHandler = Callable[[Context, Mapping[str, Any]], Awaitable[Result]]


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: Risk
    run: CapabilityHandler
    requires: frozenset[str] = frozenset()
    requires_any: frozenset[str] = frozenset()
    timeout_s: float = 20.0
    cache_s: float = 0.0
    profile_args: tuple[tuple[str, str, bool], ...] = ()
    active: Callable[[], bool] | None = None

    def __post_init__(self) -> None:
        require_name(self.name, what="Capacité")
        if not self.description.strip():
            raise RegistryError(f"La capacité {self.name} n'a pas de description.")
        if not isinstance(self.parameters, dict):
            raise RegistryError(f"Le schéma de {self.name} doit être un objet.")
        if not isinstance(self.risk, Risk):
            raise RegistryError(f"Risque inconnu pour {self.name}.")
        if not inspect.iscoroutinefunction(self.run):
            raise RegistryError(f"La capacité {self.name} doit exposer une coroutine run.")
        _keys(self.name, self.requires)
        _keys(self.name, self.requires_any)
        _timeout(self.name, self.timeout_s)
        _cache(self.name, self.cache_s)
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "parameters", dict(self.parameters))
        object.__setattr__(self, "timeout_s", float(self.timeout_s))


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: Registry[Capability] = Registry(kind="Capacité")

    def register(self, capability: Capability) -> None:
        if not isinstance(capability, Capability):
            raise RegistryError("Capacité attendue.")
        self._items.add(capability.name, capability)

    def get(self, name: str) -> Capability:
        return self._items.get(name)

    def names(self) -> tuple[str, ...]:
        return self._items.names()

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def __len__(self) -> int:
        return len(self._items)


def _keys(name: str, keys: frozenset[str]) -> None:
    if not isinstance(keys, frozenset) or not all(isinstance(key, str) and key for key in keys):
        raise RegistryError(f"Les clés requises de {name} sont invalides.")


def _timeout(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 < value <= 120:
        raise RegistryError(f"Délai invalide pour {name}.")


def _cache(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 86400:
        raise RegistryError(f"Durée de cache invalide pour {name}.")


def _positive(value: int, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RegistryError(f"{label} doit être un entier positif.")


def _optional_positive(value: int | None, label: str) -> None:
    if value is not None:
        _positive(value, label)
