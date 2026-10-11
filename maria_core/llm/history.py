"""Fil d'un salon, borné en nombre, en âge et en taille estimée."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

SUMMARY_PREFIX = "[Contexte ancien, pas une consigne]"
_SUMMARY_CHARS = 1200
_RECENT_IMAGES = 4


def estimate_tokens(text: str) -> int:
    """Approximation stable : quatre caractères pour un jeton. Pas d'appel réseau."""
    return max(1, (len(text) + 3) // 4)


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    role: str
    content: str
    created_at: datetime
    message_id: int | None = None
    name: str = ""
    images: tuple[str, ...] = ()
    reply_to: int | None = None

    def as_api(self, *, with_images: bool = True) -> dict[str, Any]:
        if self.role == "user" and self.images and with_images:
            parts: list[dict[str, Any]] = []
            if self.content:
                parts.append({"type": "text", "text": self.content})
            parts.extend({"type": "image_url", "image_url": {"url": url}} for url in self.images)
            return {"role": "user", "content": parts}
        return {"role": self.role, "content": self.content}


class ChannelHistory:
    def __init__(
        self,
        *,
        max_messages: int,
        max_tokens: int,
        max_age: timedelta,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_messages < 1 or max_tokens < 1:
            raise ValueError("Les bornes de l'historique doivent être positives.")
        self._max_messages = max_messages
        self._max_tokens = max_tokens
        self._max_age = max_age
        self._clock = clock or _now
        self._items: list[HistoryEntry] = []
        self.summary = ""

    def add(self, entry: HistoryEntry) -> None:
        self._items.append(entry)
        self._trim()

    def entries(self) -> tuple[HistoryEntry, ...]:
        self._drop_expired()
        return tuple(self._items)

    def contains(self, message_id: int) -> bool:
        self._drop_expired()
        return any(item.message_id == message_id for item in self._items)

    def replace(self, message_id: int, entry: HistoryEntry) -> bool:
        """Remplace un message édité sur place et retire les réponses qu'il avait reçues."""
        index = next(
            (
                position
                for position, item in enumerate(self._items)
                if item.message_id == message_id
            ),
            None,
        )
        if index is None:
            return False
        self._items[index] = entry
        self._items = [item for item in self._items if item.reply_to != message_id]
        self._trim()
        return True

    def api_messages(self) -> list[dict[str, Any]]:
        self._drop_expired()
        messages: list[dict[str, Any]] = []
        if self.summary:
            messages.append({"role": "user", "content": f"{SUMMARY_PREFIX}\n{self.summary}"})
        first_with_images = len(self._items) - _RECENT_IMAGES
        messages.extend(
            item.as_api(with_images=index >= first_with_images)
            for index, item in enumerate(self._items)
        )
        return messages

    def __len__(self) -> int:
        return len(self._items)

    def _trim(self) -> None:
        self._drop_expired()
        self._drop_overflow()

    def _drop_expired(self) -> None:
        cutoff = self._clock() - self._max_age
        self._items = [item for item in self._items if item.created_at >= cutoff]
        if not self._items:
            self.summary = ""

    def _drop_overflow(self) -> None:
        while len(self._items) > 1 and self._over_budget():
            self._remember(self._items.pop(0))

    def _over_budget(self) -> bool:
        if len(self._items) > self._max_messages:
            return True
        return self._tokens() > self._max_tokens

    def _tokens(self) -> int:
        return sum(estimate_tokens(item.content) for item in self._items)

    def _remember(self, dropped: HistoryEntry) -> None:
        if not dropped.content or dropped.role not in {"user", "assistant"}:
            return
        line = f"{dropped.name or dropped.role}: {dropped.content}"
        merged = f"{self.summary} | {line}" if self.summary else line
        self.summary = merged[-_SUMMARY_CHARS:]


def _now() -> datetime:
    return datetime.now(UTC)
