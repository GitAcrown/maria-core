"""Sections du prompt, ajoutées par les extensions sans modifier le noyau."""

from collections.abc import Callable
from dataclasses import dataclass

from maria_core.errors import RegistryError
from maria_core.registry import Registry


@dataclass(frozen=True, slots=True)
class _Section:
    name: str
    order: int
    render: Callable[[], str]


class PromptSections:
    def __init__(self) -> None:
        self._items: Registry[_Section] = Registry(kind="Section")

    def register_section(
        self,
        name: str,
        render: Callable[[], str],
        *,
        order: int = 100,
    ) -> None:
        if not callable(render):
            raise RegistryError(f"La section {name} doit fournir un rendu appelable.")
        if not isinstance(order, int) or isinstance(order, bool):
            raise RegistryError("L'ordre d'une section doit être un entier.")
        self._items.add(name, _Section(name, order, render))

    def render(self) -> str:
        ordered = sorted(self._items.values(), key=lambda section: (section.order, section.name))
        parts = [section.render().strip() for section in ordered]
        return "\n\n".join(part for part in parts if part)

    def names(self) -> tuple[str, ...]:
        return self._items.names()
