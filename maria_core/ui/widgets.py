"""Rendus nommés. Le dessin Discord est dans l'adaptateur ; ici, le texte et les onglets."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from maria_core.errors import RegistryError
from maria_core.registry import Registry

logger = logging.getLogger(__name__)

type WidgetRender = Callable[[Mapping[str, Any]], str | Rendered]


@dataclass(frozen=True, slots=True)
class Rendered:
    text: str
    tabs: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", self.text.strip())
        object.__setattr__(self, "tabs", _tabs(self.tabs))


class WidgetRegistry:
    def __init__(self) -> None:
        self._items: Registry[WidgetRender] = Registry(kind="Widget")

    def register(self, name: str, render: WidgetRender) -> None:
        if not callable(render):
            raise RegistryError(f"Le widget {name} doit fournir un rendu appelable.")
        self._items.add(name, render)

    def get(self, name: str) -> WidgetRender:
        return self._items.get(name)

    def names(self) -> tuple[str, ...]:
        return self._items.names()

    def __contains__(self, name: object) -> bool:
        return name in self._items


def show(registry: WidgetRegistry, name: str, data: Mapping[str, Any]) -> Rendered | None:
    if name not in registry:
        return None
    try:
        raw = registry.get(name)(data)
    except Exception:
        logger.exception("Rendu %s en échec", name)
        return None
    if isinstance(raw, Rendered):
        return raw
    if isinstance(raw, str):
        return Rendered(raw)
    return None


def _tabs(items: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    clean: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        label, body = item
        if isinstance(label, str) and isinstance(body, str) and label.strip() and body.strip():
            clean.append((label.strip()[:80], body.strip()[:1800]))
    return tuple(clean[:8])
