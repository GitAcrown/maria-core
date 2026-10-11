"""Activité, attention et fatigue. L'horloge est injectée : le score se rejoue."""

from collections.abc import Callable
from datetime import datetime

_WINDOW = 600.0
_ATTENTION_HALF = 210.0
_FATIGUE_HALF = 480.0
_REACTION_MEMORY = 2000


class Room:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._seen: dict[int, list[tuple[int, float]]] = {}
        self._attention: dict[tuple[int, int], tuple[float, float]] = {}
        self._fatigue: dict[tuple[int, int], tuple[float, float]] = {}
        self._last_react: dict[int, float] = {}
        self._follow: dict[tuple[int, int], tuple[float, int]] = {}
        self._reaction_users: dict[tuple[int, str], set[int]] = {}
        self._joined: dict[tuple[int, str], None] = {}

    def now(self) -> float:
        return self._clock().timestamp()

    def note(self, channel_id: int, author_id: int) -> None:
        stamp = self.now()
        recent = [item for item in self._seen.get(channel_id, []) if stamp - item[1] <= _WINDOW]
        recent.append((author_id, stamp))
        self._seen[channel_id] = recent

    def volume(self, channel_id: int) -> int:
        return len(self._recent(channel_id))

    def from_author(self, channel_id: int, author_id: int) -> int:
        return sum(1 for author, _stamp in self._recent(channel_id) if author == author_id)

    def humans(self, channel_id: int) -> int:
        return len({author for author, _stamp in self._recent(channel_id)})

    def _recent(self, channel_id: int) -> list[tuple[int, float]]:
        stamp = self.now()
        return [item for item in self._seen.get(channel_id, []) if stamp - item[1] <= _WINDOW]

    def bump_attention(self, guild_id: int, user_id: int) -> None:
        key = (guild_id, user_id)
        self._attention[key] = (min(2.0, self.attention(guild_id, user_id) + 1.0), self.now())

    def attention(self, guild_id: int, user_id: int) -> float:
        return _decay(self._attention.get((guild_id, user_id)), self.now(), _ATTENTION_HALF)

    def bump_fatigue(self, channel_id: int, user_id: int) -> None:
        key = (channel_id, user_id)
        self._fatigue[key] = (min(4.0, self.fatigue(channel_id, user_id) + 0.8), self.now())

    def fatigue(self, channel_id: int, user_id: int) -> float:
        return _decay(self._fatigue.get((channel_id, user_id)), self.now(), _FATIGUE_HALF)

    def mark_react(self, channel_id: int) -> None:
        self._last_react[channel_id] = self.now()

    def reacted_recently(self, channel_id: int) -> bool:
        stamp = self._last_react.get(channel_id)
        return stamp is not None and self.now() - stamp <= _WINDOW

    def open_followup(self, channel_id: int, author_id: int) -> None:
        key = (channel_id, author_id)
        previous = self._follow.get(key)
        depth = 0 if previous is None else previous[1] + 1
        self._follow[key] = (self.now(), depth)

    def followup(self, channel_id: int, author_id: int) -> tuple[float, int] | None:
        found = self._follow.get((channel_id, author_id))
        if found is None:
            return None
        return self.now() - found[0], found[1]

    def add_human_reaction(self, message_id: int, emoji: str, user_id: int) -> int:
        users = self._reaction_users.setdefault((message_id, emoji), set())
        users.add(user_id)
        _cap(self._reaction_users)
        return len(users)

    def joined(self, message_id: int, emoji: str) -> bool:
        return (message_id, emoji) in self._joined

    def mark_joined(self, message_id: int, emoji: str) -> None:
        self._joined[(message_id, emoji)] = None
        _cap(self._joined)

    def tracked_reactions(self) -> int:
        return len(self._reaction_users) + len(self._joined)


def _cap[K, V](items: dict[K, V]) -> None:
    while len(items) > _REACTION_MEMORY:
        items.pop(next(iter(items)))


def _decay(entry: tuple[float, float] | None, now: float, half_life: float) -> float:
    if entry is None:
        return 0.0
    value, stamp = entry
    elapsed = max(0.0, now - stamp)
    return value * 0.5 ** (elapsed / half_life)
