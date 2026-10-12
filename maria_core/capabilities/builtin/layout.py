"""render_widget et render_table : MARIA compose elle-même une vue ou un tableau."""

from collections.abc import Mapping
from typing import Any

from maria_core.capabilities.base import Capability, Context, Result, Risk
from maria_core.ui.widgets import (
    Block,
    Card,
    Rendered,
    card,
    footer,
    gallery,
    heading,
    links,
    separator,
    stats,
    text,
    thumbnail,
)

_MAX_ROWS = 25
_MAX_COLUMNS = 6
_CELL = 24

_WIDGET_TEXT = (
    "Compose une vue Discord sur mesure (blocs : text, separator, stat_row, thumbnail, gallery, "
    "footer, links). À utiliser quand la personne demande une fiche, une carte, un comparatif, "
    "une recette, un tuto, un classement, ou une mise en forme précise : suis exactement ce "
    "qu'elle demande (titre, couleur, ordre, images, boutons). Pas pour une question directe "
    "ni un avis : là, réponds en texte. Le widget EST la réponse : ne le recopie pas autour. "
    "Plusieurs appels dans le même tour = plusieurs cartes dans un seul message. "
    "Images : seulement des URLs déjà fiables (résultat d'outil, avatar, lien du message). "
    'Exemple : {"title":"PS5 vs Xbox","emoji":"🎮","accent":"#2b6cb0","blocks":['
    '{"type":"stat_row","items":[{"label":"Prix","value":"499 €"}]},'
    '{"type":"separator"},{"type":"text","content":"**PS5** : exclusivités."},'
    '{"type":"footer","content":"Avis MARIA"}]}'
)
_TABLE_TEXT = (
    "Affiche un tableau aligné (bloc de code) dans le salon. Dès qu'une réponse mérite un "
    "tableau lisible. Ne recopie pas le tableau dans ta réponse : il est posté tel quel."
)


def layout_capabilities() -> tuple[Capability, ...]:
    return (
        Capability(
            name="render_widget",
            description=_WIDGET_TEXT,
            parameters=_widget_schema(),
            risk=Risk.READ,
            run=_widget,
        ),
        Capability(
            name="render_table",
            description=_TABLE_TEXT,
            parameters=_table_schema(),
            risk=Risk.READ,
            run=_table,
        ),
    )


def render_widget(data: Mapping[str, Any]) -> Rendered:
    built = card_from_spec(data)
    return Rendered(cards=(built,), note=str(data.get("note") or ""))


def render_table(data: Mapping[str, Any]) -> Rendered:
    table = str(data.get("table") or "")
    return Rendered(f"```\n{table}\n```" if table else "", note="Tableau affiché.")


async def _widget(_context: Context, args: Mapping[str, Any]) -> Result:
    built = card_from_spec(args)
    if not built.blocks:
        return Result(ok=False, data={}, error="Widget vide : ajoute au moins un bloc.")
    note = f"Widget affiché : {str(args.get('title') or 'sans titre')[:80]}."
    return Result(ok=True, data={**dict(args), "note": note}, widget="render_widget")


async def _table(_context: Context, args: Mapping[str, Any]) -> Result:
    rows = [[_cell(value) for value in row[:_MAX_COLUMNS]] for row in args.get("rows") or []]
    headers = [_cell(value) for value in (args.get("headers") or [])[:_MAX_COLUMNS]]
    if not rows:
        return Result(ok=False, data={}, error="Tableau vide.")
    table = format_table(headers, rows[:_MAX_ROWS])
    return Result(ok=True, data={"table": table, "rows": len(rows)}, widget="render_table")


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    width = max([len(headers), *(len(row) for row in rows)])
    grid = [row + [""] * (width - len(row)) for row in ([headers] if headers else []) + rows]
    sizes = [max(len(line[index]) for line in grid) for index in range(width)]
    lines = [" | ".join(cell.ljust(sizes[i]) for i, cell in enumerate(line)) for line in grid]
    if headers:
        lines.insert(1, "-+-".join("-" * size for size in sizes))
    return "\n".join(line.rstrip() for line in lines)


def card_from_spec(spec: Mapping[str, Any]) -> Card:
    blocks: list[Block | None] = []
    title = str(spec.get("title") or "").strip()
    if title:
        blocks.append(heading(title, emoji=str(spec.get("emoji") or "").strip()))
    for raw in spec.get("blocks") or []:
        if isinstance(raw, Mapping):
            blocks.append(_block(raw))
    return card(*blocks, accent=_accent(spec.get("accent")))


def _block(raw: Mapping[str, Any]) -> Block | None:
    kind = str(raw.get("type") or "")
    content = str(raw.get("content") or "")
    if kind == "text":
        return text(content)
    if kind == "separator":
        return separator()
    if kind == "stat_row":
        return stats([(str(i.get("label") or ""), str(i.get("value") or "")) for i in _dicts(raw)])
    if kind == "thumbnail":
        return thumbnail(content, str(raw.get("url") or ""))
    if kind == "gallery":
        return gallery([str(url) for url in raw.get("urls") or []])
    if kind == "footer":
        return footer(content)
    if kind == "links":
        return links([(str(i.get("label") or ""), str(i.get("url") or "")) for i in _dicts(raw)])
    return None


def _dicts(raw: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item for item in raw.get("items") or [] if isinstance(item, Mapping)]


def _accent(raw: object) -> int | None:
    value = str(raw or "").strip().lstrip("#")
    if len(value) != 6:
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def _cell(value: object) -> str:
    cleaned = " ".join(str(value or "").split())
    return cleaned if len(cleaned) <= _CELL else cleaned[: _CELL - 1] + "…"


def _widget_schema() -> dict[str, Any]:
    item = {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "value": {"type": "string", "description": "Valeur (stat_row)"},
            "url": {"type": "string", "description": "URL du bouton (links)"},
        },
        "required": ["label"],
    }
    block = {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": [
                    "text",
                    "separator",
                    "stat_row",
                    "thumbnail",
                    "gallery",
                    "footer",
                    "links",
                ],
            },
            "content": {"type": "string", "description": "Markdown (text, thumbnail, footer)"},
            "url": {"type": "string", "description": "Image de la vignette (thumbnail)"},
            "urls": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
            "items": {"type": "array", "items": item, "maxItems": 6},
        },
        "required": ["type"],
    }
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "emoji": {"type": "string"},
            "accent": {
                "type": "string",
                "description": "Couleur de barre, seulement si la personne en demande une",
            },
            "blocks": {"type": "array", "items": block, "minItems": 1, "maxItems": 16},
        },
        "required": ["blocks"],
    }


def _table_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "headers": {"type": "array", "items": {"type": "string"}},
            "rows": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "string"}},
            },
        },
        "required": ["rows"],
    }
