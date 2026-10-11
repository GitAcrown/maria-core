"""Souvenirs actifs, propositions encore ouvertes. Le reste est listé."""

import sqlite3
from datetime import datetime

from maria_core.legacy.model import MemoryDraft, ProposalDraft, Skip
from maria_core.legacy.read import cell, moment, positive
from maria_core.memory.text import normalize

_SOURCE = "souvenir"


def convert_memories(
    rows: list[sqlite3.Row] | None,
    *,
    now: datetime,
) -> tuple[tuple[MemoryDraft, ...], tuple[ProposalDraft, ...], tuple[Skip, ...]]:
    memories: list[MemoryDraft] = []
    proposals: list[ProposalDraft] = []
    skips: list[Skip] = []
    seen_self: set[str] = set()
    for row in rows or []:
        _place(row, memories, proposals, skips, seen_self, now)
    return tuple(memories), tuple(proposals), tuple(skips)


def _place(
    row: sqlite3.Row,
    memories: list[MemoryDraft],
    proposals: list[ProposalDraft],
    skips: list[Skip],
    seen_self: set[str],
    now: datetime,
) -> None:
    status = str(cell(row, "status", "") or "").strip()
    if status == "archived":
        skips.append(_skip(row, "archivé", loud=False))
        return
    if str(cell(row, "category", "")).strip() == "event":
        skips.append(_skip(row, "catégorie event", loud=False))
        return
    content = str(cell(row, "content", "")).strip()
    if not content:
        skips.append(_skip(row, "souvenir vide"))
        return
    located = _scope(row)
    if isinstance(located, Skip):
        skips.append(located)
        return
    scope, subject, guild = located
    created = moment(cell(row, "created_at", "")) or moment(cell(row, "confirmed_at", "")) or now
    if status == "pending":
        proposals.append(_proposal(row, scope, subject, guild, content, created))
        return
    if status != "active":
        skips.append(_skip(row, f"statut inconnu ({status})"))
        return
    if scope == "self" and normalize(content) in seen_self:
        skips.append(_skip(row, "souvenir self déjà repris"))
        return
    if scope == "self":
        seen_self.add(normalize(content))
    memories.append(_memory(row, scope, subject, guild, content, created))


def _scope(row: sqlite3.Row) -> tuple[str, int, int | None] | Skip:
    category = str(cell(row, "category", "")).strip()
    guild = positive(cell(row, "guild_id", 0))
    user = positive(cell(row, "user_id", 0))
    if category == "user":
        return (user and ("user", user, guild)) or _skip(row, "souvenir perso sans auteur")
    if category == "server":
        return (guild and ("guild", guild, guild)) or _skip(row, "souvenir de serveur sans serveur")
    if category == "self":
        return "self", 0, None
    return _skip(row, f"catégorie inconnue ({category or 'vide'})")


def _memory(
    row: sqlite3.Row,
    scope: str,
    subject: int,
    guild: int | None,
    content: str,
    created: datetime,
) -> MemoryDraft:
    author = positive(cell(row, "user_id", 0)) or 0
    chroma = str(cell(row, "chroma_id", "") or "").strip() or str(cell(row, "id", "")).strip()
    return MemoryDraft(
        legacy_id=str(cell(row, "id", "?")),
        scope=scope,
        subject_id=subject,
        guild_id=guild,
        content=content,
        created_by=author,
        created_at=created.isoformat(),
        chroma_id=chroma,
    )


def _proposal(
    row: sqlite3.Row,
    scope: str,
    subject: int,
    guild: int | None,
    content: str,
    created: datetime,
) -> ProposalDraft:
    who = subject if scope == "user" else positive(cell(row, "user_id", 0))
    return ProposalDraft(
        legacy_id=str(cell(row, "id", "?")),
        guild_id=guild,
        subject_user_id=who,
        scope=scope,
        content=content,
        confidence=_confidence(cell(row, "confidence", "")),
        created_at=created.isoformat(),
    )


def _confidence(raw: object) -> float | None:
    try:
        return float(str(raw))
    except ValueError:
        return None


def _skip(row: sqlite3.Row, reason: str, *, loud: bool = True) -> Skip:
    return Skip(_SOURCE, str(cell(row, "id", "?")), reason, loud)
