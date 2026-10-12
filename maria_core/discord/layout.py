"""Cartes neutres -> Components v2. Une vue par message, découpée sous les limites Discord."""

import logging
import re

import discord

from maria_core.ui.widgets import Block, Card

logger = logging.getLogger(__name__)

TEXT_BUDGET = 3800
COMPONENT_BUDGET = 38
_URL = re.compile(r"(?<![<(])(https?://[^\s>)]+)")


def quiet_links(text: str) -> str:
    """Entoure les URLs nues de <> : Discord n'affiche pas d'aperçu."""
    return _URL.sub(r"<\1>", text or "")


def build_views(
    *,
    intro: str,
    cards: tuple[Card, ...],
    outro: str = "",
) -> list[discord.ui.LayoutView]:
    """Commentaire, puis une carte par conteneur, puis le pied. Plusieurs vues si trop gros."""
    pages: list[list[discord.ui.Item]] = [[]]
    budget = {"text": 0, "items": 0}

    def push(item: discord.ui.Item, chars: int, weight: int) -> None:
        if pages[-1] and (
            budget["text"] + chars > TEXT_BUDGET or budget["items"] + weight > COMPONENT_BUDGET
        ):
            pages.append([])
            budget["text"] = budget["items"] = 0
        pages[-1].append(item)
        budget["text"] += chars
        budget["items"] += weight

    if intro.strip():
        body = intro.strip()[:TEXT_BUDGET]
        push(discord.ui.TextDisplay(quiet_links(body)), len(body), 1)
    for item in cards:
        container, chars, weight = _container(item)
        if container is not None:
            push(container, chars, weight)
    if outro.strip():
        body = outro.strip()[:TEXT_BUDGET]
        push(discord.ui.TextDisplay(quiet_links(body)), len(body), 1)
    return [_view(page) for page in pages if page]


def _view(items: list[discord.ui.Item]) -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=None)
    for item in items:
        view.add_item(item)
    return view


def _container(item: Card) -> tuple[discord.ui.Container | None, int, int]:
    children: list[discord.ui.Item] = []
    chars = 0
    for block in item.blocks:
        built = _block(block)
        if built is None:
            continue
        children.append(built)
        chars += len(block.text) + sum(len(label) for label, _value in block.pairs)
    if not children:
        return None, 0, 0
    kwargs: dict[str, object] = {}
    if item.accent is not None:
        kwargs["accent_colour"] = discord.Colour(item.accent)
    weight = 1 + sum(_weight(child) for child in children)
    return discord.ui.Container(*children, **kwargs), chars, weight


def _block(block: Block) -> discord.ui.Item | None:
    builder = _BUILDERS.get(block.kind)
    if builder is None:
        return None
    try:
        return builder(block)
    except (TypeError, ValueError):
        logger.warning("Bloc %s ignoré", block.kind, exc_info=True)
        return None


def _text(block: Block) -> discord.ui.Item | None:
    if not block.text:
        return None
    return discord.ui.TextDisplay(quiet_links(block.text[:TEXT_BUDGET]))


def _separator(_block: Block) -> discord.ui.Item:
    return discord.ui.Separator(spacing=discord.SeparatorSpacing.small)


def _stats(block: Block) -> discord.ui.Item | None:
    line = block.as_text()
    return discord.ui.TextDisplay(line) if line else None


def _thumbnail(block: Block) -> discord.ui.Item:
    return discord.ui.Section(
        discord.ui.TextDisplay(quiet_links(block.text[:TEXT_BUDGET])),
        accessory=discord.ui.Thumbnail(block.url),
    )


def _gallery(block: Block) -> discord.ui.Item | None:
    if not block.urls:
        return None
    media = discord.ui.MediaGallery()
    for url in block.urls:
        media.add_item(media=url)
    return media


def _footer(block: Block) -> discord.ui.Item | None:
    if not block.text:
        return None
    return discord.ui.TextDisplay(quiet_links(f"-# {block.text}"))


def _links(block: Block) -> discord.ui.Item | None:
    if not block.pairs:
        return None
    row = discord.ui.ActionRow()
    for label, url in block.pairs:
        row.add_item(discord.ui.Button(label=label, url=url, style=discord.ButtonStyle.link))
    return row


def _weight(item: discord.ui.Item) -> int:
    if isinstance(item, discord.ui.Section):
        return 3
    if isinstance(item, discord.ui.ActionRow):
        return 1 + len(item.children)
    return 1


_BUILDERS = {
    "text": _text,
    "separator": _separator,
    "stats": _stats,
    "thumbnail": _thumbnail,
    "gallery": _gallery,
    "footer": _footer,
    "links": _links,
}
