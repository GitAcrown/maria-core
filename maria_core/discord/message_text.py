"""Tout le texte lisible d'un message Discord, y compris celui des messages en composants.

Les cartes de MARIA (et d'autres bots) n'ont pas de `content` : leur texte est dans des blocs
de texte rangés dans des conteneurs. Un message transféré garde le sien dans une copie.
"""

from collections.abc import Iterable
from typing import Any


def text_of(message: Any) -> str:
    """Le texte du message, de ses aperçus, de ses composants et de sa copie transférée."""
    parts: list[str] = [str(getattr(message, "content", "") or "")]
    parts += _embeds(getattr(message, "embeds", ()) or ())
    parts += _components(getattr(message, "components", ()) or ())
    for snapshot in getattr(message, "message_snapshots", ()) or ():
        parts.append(str(getattr(snapshot, "content", "") or ""))
        parts += _embeds(getattr(snapshot, "embeds", ()) or ())
        parts += _components(getattr(snapshot, "components", ()) or ())
    return "\n\n".join(dict.fromkeys(part.strip() for part in parts if part and part.strip()))


def _embeds(embeds: Iterable[Any]) -> list[str]:
    found: list[str] = []
    for embed in embeds:
        found += [str(embed.title or ""), str(embed.description or "")]
        found += [f"{field.name} : {field.value}" for field in getattr(embed, "fields", ()) or ()]
    return found


def _components(items: Iterable[Any]) -> list[str]:
    found: list[str] = []
    for item in items:
        content = getattr(item, "content", None)
        if isinstance(content, str):
            found.append(content)
        found += _components(getattr(item, "children", ()) or ())
    return found
