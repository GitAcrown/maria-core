"""Du résultat du modèle au message posté : texte nettoyé, cartes, pied discret, notes."""

import json
from dataclasses import dataclass
from urllib.parse import urlparse

from maria_core.llm.clean import clean_reply, silence_marks
from maria_core.llm.loop import LoopResult, ToolRecord
from maria_core.ui.emojis import SLOT_ICONS
from maria_core.ui.widgets import Card, WidgetRegistry, gallery, show

UNAVAILABLE_TEXT = "Je n'arrive pas à répondre pour l'instant, réessaie dans un moment."

_QUIET = frozenset(
    {
        "search_memory",
        "search_images",
        "get_server_users",
        "get_member_info",
        "get_channel_info",
        "run_python",
        "objective_list",
        "objective_show",
        "about_me",
        "get_weather",
        "search_media",
        "search_game",
        "get_football",
        "get_transport",
        "render_table",
        "render_widget",
        "summarize_channel",
        "search_track",
        "read_youtube",
        "create_poll",
    }
)
_LABELS = {
    "search_web": ("Recherche", "query"),
    "read_web_page": ("Lecture", "url"),
    "remember_fact": ("Retenu", "content"),
    "forget_fact": ("Oublié", ""),
}
_NOTE_CHARS = 360
_MERGED_IMAGES = 4


@dataclass(frozen=True, slots=True)
class Composed:
    text: str
    cards: tuple[Card, ...]
    footer: str
    notes: tuple[str, ...]
    react: bool
    skip: bool
    sources: bool = False


def compose(outcome: LoopResult, widgets: WidgetRegistry, bot_names: tuple[str, ...]) -> Composed:
    if not outcome.ok:
        return Composed(UNAVAILABLE_TEXT, (), "", (), False, False)
    raw, react, skip = silence_marks(outcome.text)
    text = clean_reply(raw, bot_names)
    parts = [text] if text else []
    cards: list[Card] = []
    notes: list[str] = []
    for record in outcome.records:
        note = _record(record, widgets, parts, cards)
        if note:
            notes.append(note)
    footer = _footer(outcome.records)
    body = "\n\n".join(part for part in parts if part).strip()
    return Composed(
        body, tuple(_merge_galleries(cards)), footer, tuple(notes), react, skip, bool(footer)
    )


def _merge_galleries(cards: list[Card]) -> list[Card]:
    """Plusieurs search_images dans le même tour : une seule galerie, comme dans MARIA_R."""
    loose = [item for item in cards if _is_gallery(item)]
    if len(loose) < 2:
        return cards
    urls = [url for item in loose for url in item.blocks[0].urls][:_MERGED_IMAGES]
    captions = {label_url: label for item in loose for label, label_url in item.blocks[0].pairs}
    merged = Card((gallery(urls, captions),), None, True)
    kept = [item for item in cards if not _is_gallery(item)]
    first = next(index for index, item in enumerate(cards) if _is_gallery(item))
    kept.insert(min(first, len(kept)), merged)
    return kept


def _is_gallery(item: Card) -> bool:
    return item.bare and len(item.blocks) == 1 and item.blocks[0].kind == "gallery"


def _record(
    record: ToolRecord, widgets: WidgetRegistry, parts: list[str], cards: list[Card]
) -> str:
    result = record.result
    if not result.ok:
        return ""
    rendered = show(widgets, result.widget, result.data) if result.widget else None
    if rendered is not None:
        if rendered.text:
            parts.append(rendered.text)
        cards.extend(rendered.cards)
        if rendered.note:
            return f"{record.name} : {rendered.note[:_NOTE_CHARS]}"
    return f"{record.name} : {_summary(result.data)}"


def _summary(data: object) -> str:
    try:
        raw = json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raw = str(data)
    return raw[:_NOTE_CHARS]


def _footer(records: tuple[ToolRecord, ...]) -> str:
    lines: list[str] = []
    sources = _sources(records)
    for record in records:
        label = _label(record)
        if label and label not in lines:
            lines.append(label)
    lines.extend(_profile_lines(records))
    if sources:
        title = "Sources" if len(sources) > 1 else "Source"
        lines.append(f"**{title}** · " + " · ".join(sources))
    return "\n".join(f"-# {line}" for line in lines)


def _profile_lines(records: tuple[ToolRecord, ...]) -> list[str]:
    """« 🏠 Lyon · ville de ton profil » : la personne voit ce qui a été pris dans son profil."""
    seen: dict[str, str] = {}
    for record in records:
        if not record.result.ok:
            continue
        for mark in record.result.data.get("profile_used") or []:
            icon = SLOT_ICONS.get(str(mark.get("slot")), "👤")
            seen[str(mark.get("slot"))] = (
                f"{icon} {mark.get('value')} · {str(mark.get('label')).lower()} de ton profil"
            )
    return list(seen.values())


def _label(record: ToolRecord) -> str:
    if record.name in _QUIET or not record.result.ok:
        return ""
    if record.name in {"search_web", "read_web_page"} and _sources((record,)):
        return ""
    if record.name in {"objective_create", "objective_update"}:
        return _objective_label(record)
    title, field = _LABELS.get(record.name, ("", ""))
    if not title:
        words = [word.capitalize() for word in record.name.split("_") if word]
        return f"**{' '.join(words[:2]) or 'Outil'}**"
    detail = _clip(str(record.arguments.get(field) or "")) if field else ""
    if field == "url":
        return f"**{title}** · {_domain(str(record.arguments.get(field) or ''))}"
    return f"**{title}** · « {detail} »" if detail else f"**{title}**"


def _objective_label(record: ToolRecord) -> str:
    """Rappel, Écoute, Surveillance… plutôt qu'un « Objectif » générique."""
    data = record.result.data
    kind = str(data.get("kind") or "Objectif")
    if record.name == "objective_update":
        done = str(data.get("done") or "")
        return f"**{kind}** · {done}" if done else f"**{kind}**"
    title = _clip(str(data.get("title") or record.arguments.get("title") or ""))
    when = str(data.get("when") or "")
    draft = data.get("status") == "draft"
    tail = " · réponds « oui » ou « non »" if draft else (f" · {when}" if when else "")
    return f"**{kind}** · « {title} »{tail}" if title else f"**{kind}**"


def _sources(records: tuple[ToolRecord, ...]) -> list[str]:
    seen: set[str] = set()
    found: list[str] = []
    for record in records:
        if not record.result.ok:
            continue
        urls = [source.url for source in record.result.sources]
        if record.name == "read_web_page":
            urls.append(str(record.result.data.get("url") or ""))
        for url in urls:
            domain = _domain(url)
            if domain and domain not in seen:
                seen.add(domain)
                found.append(f"[{domain}](<{url}>)")
    return found[:3]


def _domain(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").lower()
    except ValueError:
        return ""
    return host.removeprefix("www.")


def _clip(text: str, limit: int = 40) -> str:
    cleaned = " ".join(text.split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"
