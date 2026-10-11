"""Commandes déclarées par les extensions, indépendantes de Discord."""

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from maria_core.errors import RegistryError
from maria_core.registry import Registry


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    description: str
    handler: Callable[..., Awaitable[None]]


class CommandCatalog:
    def __init__(self) -> None:
        self._items: Registry[CommandSpec] = Registry(kind="Commande")

    def add(self, name: str, description: str, handler: Callable[..., Awaitable[None]]) -> None:
        text = description.strip()
        if not text:
            raise RegistryError("La commande doit avoir une description.")
        if not inspect.iscoroutinefunction(handler):
            raise RegistryError(f"La commande {name} doit être une coroutine.")
        self._items.add(name, CommandSpec(name, text, handler))

    def get(self, name: str) -> CommandSpec:
        return self._items.get(name)

    def names(self) -> tuple[str, ...]:
        return self._items.names()

    def __contains__(self, name: object) -> bool:
        return name in self._items
