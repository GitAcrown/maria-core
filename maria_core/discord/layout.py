"""Cartes neutres -> Components v2, mises en page comme dans MARIA_R. Découpe sous les limites."""

import logging
import re

import discord

from maria_core.ui.emojis import downgrade
from maria_core.ui.widgets import Block, Card

logger = logging.getLogger(__name__)

TEXT_BUDGET = 3800
COMPONENT_BUDGET = 38
_URL = re.compile(r"(?<![<(])(https?://[^\s<>)]+)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?!<)(https?://[^)\s]+)\)")
_EMOJIS: dict[str, frozenset[int] | None] = {"usable": None}


def use_emojis(ids: set[int] | frozenset[int]) -> None:
    """Emojis custom accessibles au bot ; les autres passent en Unicode."""
    _EMOJIS["usable"] = frozenset(ids)


def emojis(text: str) -> str:
    return downgrade(text, _EMOJIS["usable"])


def quiet_links(text: str) -> str:
    """Liens sans aperçu Discord : `[texte](<url>)` et URLs nues entre <>."""
    value = _MD_LINK.sub(lambda match: f"[{match.group(1)}](<{match.group(2)}>)", text or "")
    return _URL.sub(_bare, emojis(value))


def build_views(
    *,
    intro: str,
    cards: tuple[Card, ...],
    outro: str = "",
) -> list[discord.ui.LayoutView]:
    """Commentaire et trait fin, puis les cartes, puis le pied. Plusieurs vues si trop gros."""
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
        push(_thin(), 0, 1)
    for item in cards:
        for built, chars, weight in _placed(item):
            push(built, chars, weight)
    if outro.strip():
        body = outro.strip()[:TEXT_BUDGET]
        push(discord.ui.TextDisplay(quiet_links(body)), len(body), 1)
    return [_view(page) for page in pages if page]


def _placed(item: Card) -> list[tuple[discord.ui.Item, int, int]]:
    """Une carte devient un conteneur ; une carte `bare` pose ses blocs à nu."""
    children = [(built, _chars(block)) for block in item.blocks if (built := _block(block))]
    if not children:
        return []
    if item.bare:
        return [(built, chars, _weight(built)) for built, chars in children]
    kwargs: dict[str, object] = {}
    if item.accent is not None:
        kwargs["accent_colour"] = discord.Colour(item.accent)
    container = discord.ui.Container(*(built for built, _chars_ in children), **kwargs)
    weight = 1 + sum(_weight(built) for built, _chars_ in children)
    return [(container, sum(chars for _built, chars in children), weight)]


def _view(items: list[discord.ui.Item]) -> discord.ui.LayoutView:
    view = discord.ui.LayoutView(timeout=None)
    for item in items:
        view.add_item(item)
    return view


def _block(block: Block) -> discord.ui.Item | None:
    builder = _BUILDERS.get(block.kind)
    if builder is None:
        return None
    try:
        return builder(block)
    except (TypeError, ValueError):
        logger.warning("Bloc %s ignoré", block.kind, exc_info=True)
        return None


def _chars(block: Block) -> int:
    return len(block.text) + sum(len(label) for label, _value in block.pairs)


def _text(block: Block) -> discord.ui.Item | None:
    if not block.text:
        return None
    return discord.ui.TextDisplay(quiet_links(block.text[:TEXT_BUDGET]))


def _separator(block: Block) -> discord.ui.Item:
    if block.text == "wide":
        return discord.ui.Separator(spacing=discord.SeparatorSpacing.large)
    return _thin()


def _thin() -> discord.ui.Separator:
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
    descriptions = dict((url, label) for label, url in block.pairs)
    for url in block.urls:
        media.add_item(media=url, description=descriptions.get(url) or None)
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


def _bare(match: re.Match[str]) -> str:
    url = match.group(1)
    trail = ""
    while url and url[-1] in ".,;:!?":
        trail = url[-1] + trail
        url = url[:-1]
    return f"<{url}>{trail}" if url else match.group(0)


_BUILDERS = {
    "text": _text,
    "separator": _separator,
    "stats": _stats,
    "thumbnail": _thumbnail,
    "gallery": _gallery,
    "footer": _footer,
    "links": _links,
}
