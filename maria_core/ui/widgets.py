"""Rendus nommés. Ici, des cartes neutres ; l'adaptateur Discord les dessine en Components v2."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from maria_core.errors import RegistryError
from maria_core.registry import Registry

logger = logging.getLogger(__name__)

BLOCK_KINDS = frozenset({"text", "separator", "stats", "thumbnail", "gallery", "footer", "links"})
MAX_BLOCKS = 16
MAX_GALLERY = 10
MAX_LINKS = 5


@dataclass(frozen=True, slots=True)
class Block:
    """Un bloc de carte. `pairs` sert aux statistiques et aux liens (libellé, valeur ou URL)."""

    kind: str
    text: str = ""
    url: str = ""
    urls: tuple[str, ...] = ()
    pairs: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in BLOCK_KINDS:
            raise ValueError(f"Bloc inconnu : {self.kind}")

    def as_text(self) -> str:
        if self.kind == "separator":
            return ""
        if self.kind == "stats":
            return "  ·  ".join(f"**{label}** {value}".strip() for label, value in self.pairs)
        if self.kind == "gallery":
            return "\n".join(self.urls)
        if self.kind == "links":
            return " · ".join(f"[{label}](<{url}>)" for label, url in self.pairs)
        if self.kind == "footer":
            return f"-# {self.text}" if self.text else ""
        return self.text


@dataclass(frozen=True, slots=True)
class Card:
    """Un conteneur. `accent` est une couleur 0xRRGGBB."""

    blocks: tuple[Block, ...]
    accent: int | None = None
    bare: bool = False

    def as_text(self) -> str:
        parts = [block.as_text() for block in self.blocks]
        return "\n".join(part for part in parts if part).strip()


@dataclass(frozen=True, slots=True)
class Rendered:
    """`text` s'ajoute à la réponse, `cards` deviennent une vue, `note` reste dans l'historique."""

    text: str = ""
    cards: tuple[Card, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", self.text.strip())
        object.__setattr__(self, "cards", tuple(card for card in self.cards if card.blocks))


type WidgetRender = Callable[[Mapping[str, Any]], str | Rendered | Card | None]


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
    if isinstance(raw, Card):
        return Rendered(cards=(raw,))
    if isinstance(raw, str):
        return Rendered(raw)
    return None


def heading(title: str, meta: str = "", *, emoji: str = "") -> Block:
    head = f"## {emoji} {title}".strip() if emoji else f"## {title}"
    return Block("text", f"{head}\n-# {meta}" if meta else head)


def text(content: str) -> Block:
    return Block("text", content.strip())


def separator(*, wide: bool = False) -> Block:
    """Trait fin entre deux blocs ; large sous un titre."""
    return Block("separator", "wide" if wide else "")


def stats(pairs: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> Block:
    kept = tuple((str(label), str(value)) for label, value in pairs if str(value).strip())
    return Block("stats", pairs=kept[:6])


def thumbnail(content: str, url: str) -> Block:
    if not _is_url(url):
        return text(content)
    return Block("thumbnail", content.strip(), url=url)


def gallery(urls: list[str] | tuple[str, ...], captions: dict[str, str] | None = None) -> Block:
    """Images ; `captions` associe une légende à une URL."""
    kept = tuple(url for url in urls if _is_url(url))[:MAX_GALLERY]
    notes = tuple((captions[url][:256], url) for url in kept if captions and captions.get(url))
    return Block("gallery", urls=kept, pairs=notes)


def footer(content: str) -> Block:
    return Block("footer", content.strip())


def links(pairs: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> Block:
    kept = tuple((label[:80], url) for label, url in pairs if label and _is_url(url))
    return Block("links", pairs=kept[:MAX_LINKS])


def card(*blocks: Block | None, accent: int | None = None, bare: bool = False) -> Card:
    """`bare` : les blocs sont posés tels quels, sans conteneur (une galerie seule)."""
    kept = tuple(block for block in blocks if block is not None and _filled(block))
    return Card(kept[:MAX_BLOCKS], accent, bare)


def _filled(block: Block) -> bool:
    if block.kind == "separator":
        return True
    return bool(block.text or block.urls or block.pairs)


def _is_url(url: str) -> bool:
    return isinstance(url, str) and url.startswith(("https://", "http://"))


def quote(content: str) -> str:
    """Résumé en citation italique, comme les fiches de CRIT."""
    lines = [line.strip() for line in content.strip().splitlines()]
    return "\n".join(f"> *{line}*" if line else ">" for line in lines)


def joined(*parts: object) -> str:
    """Méta et pieds : éléments non vides séparés par un point médian aéré."""
    return "  ·  ".join(str(part) for part in parts if part)


def grouped(value: int) -> str:
    """1234567 -> « 1 234 567 » (espace fine insécable)."""
    return f"{value:,}".replace(",", "\u202f")
