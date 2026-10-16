"""Activité, attention et fatigue. L'horloge est injectée : le score se rejoue."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

_WINDOW = 600.0
_ATTENTION_HALF = 210.0
_FATIGUE_HALF = 480.0
_REACTION_MEMORY = 2000
_TEXT_MEMORY = 600
_CHAIN_GAP = 180.0
FOLLOWUP_MAX_S = 120.0  # on n'écoute jamais un suivi au-delà de 2 min après la réponse
ATTENTION_WARM = 0.9
ATTENTION_HOT = 1.8
MAX_ATTENTION = 6.0
_COMPETITIVE = 0.85
FATIGUE_BUMP = 0.4
FATIGUE_TIRED = 5.0
FATIGUE_EXHAUSTED = 8.0


@dataclass(slots=True)
class Followup:
    opened: float
    depth: int
    bot_text: str
    active: float = 0.0  # la dernière fois que la personne a écrit ou tapé


@dataclass(frozen=True, slots=True)
class Seen:
    """Un message récent : auteur, bot ou non, extrait, heure."""

    author_id: int
    from_bot: bool
    text: str
    at: float


class Room:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._seen: dict[int, list[tuple[int, float]]] = {}
        self._attention: dict[tuple[int, int], tuple[float, float]] = {}
        self._fatigue: dict[tuple[int, int], tuple[float, float]] = {}
        self._last_react: dict[int, float] = {}
        self._follow: dict[tuple[int, int], Followup] = {}
        self._reaction_users: dict[tuple[int, str], set[int]] = {}
        self._joined: dict[tuple[int, str], None] = {}
        self._messages: dict[int, Seen] = {}

    def now(self) -> float:
        return self._clock().timestamp()

    def note(self, channel_id: int, author_id: int) -> None:
        stamp = self.now()
        recent = [item for item in self._seen.get(channel_id, []) if stamp - item[1] <= _WINDOW]
        recent.append((author_id, stamp))
        self._seen[channel_id] = recent

    def remember_message(self, message_id: int, author_id: int, from_bot: bool, text: str) -> None:
        self._messages[message_id] = Seen(author_id, from_bot, text[:400], self.now())
        _cap(self._messages, _TEXT_MEMORY)

    def message(self, message_id: int) -> Seen | None:
        return self._messages.get(message_id)

    def volume(self, channel_id: int) -> int:
        return len(self._recent(channel_id))

    def from_author(self, channel_id: int, author_id: int) -> int:
        return sum(1 for author, _stamp in self._recent(channel_id) if author == author_id)

    def humans(self, channel_id: int) -> int:
        return len({author for author, _stamp in self._recent(channel_id)})

    def _recent(self, channel_id: int) -> list[tuple[int, float]]:
        stamp = self.now()
        return [item for item in self._seen.get(channel_id, []) if stamp - item[1] <= _WINDOW]

    def bump_attention(self, guild_id: int, user_id: int, amount: float = 1.0) -> None:
        """Se tourner vers quelqu'un détourne un peu des autres."""
        stamp = self.now()
        for key in [key for key in self._attention if key[0] == guild_id and key[1] != user_id]:
            value = self.attention(*key) * _COMPETITIVE
            if value < 0.05:
                self._attention.pop(key, None)
            else:
                self._attention[key] = (value, stamp)
        value = min(MAX_ATTENTION, self.attention(guild_id, user_id) + amount)
        self._attention[(guild_id, user_id)] = (value, stamp)
        _cap(self._attention, _REACTION_MEMORY)

    def attention(self, guild_id: int, user_id: int) -> float:
        return _decay(self._attention.get((guild_id, user_id)), self.now(), _ATTENTION_HALF)

    def is_hot(self, guild_id: int, user_id: int) -> bool:
        return self.attention(guild_id, user_id) >= ATTENTION_HOT

    def bump_fatigue(self, channel_id: int, user_id: int, amount: float = FATIGUE_BUMP) -> None:
        value = min(10.0, self.fatigue(channel_id, user_id) + amount)
        self._fatigue[(channel_id, user_id)] = (value, self.now())
        _cap(self._fatigue, _REACTION_MEMORY)

    def fatigue(self, channel_id: int, user_id: int) -> float:
        return _decay(self._fatigue.get((channel_id, user_id)), self.now(), _FATIGUE_HALF)

    def mark_react(self, channel_id: int) -> None:
        self._last_react[channel_id] = self.now()

    def reacted_recently(self, channel_id: int, within: float = _WINDOW) -> bool:
        stamp = self._last_react.get(channel_id)
        return stamp is not None and self.now() - stamp <= within

    def open_followup(
        self, channel_id: int, author_id: int, bot_text: str, *, chain: bool = True
    ) -> None:
        """Une chaîne se poursuit si la réponse précédente est récente, sinon elle repart à 0.

        `chain` faux : la personne vient de l'appeler elle-même, la chaîne repart à 0.
        """
        key = (channel_id, author_id)
        previous = self._follow.get(key)
        stamp = self.now()
        chained = chain and previous is not None and stamp - previous.opened <= _CHAIN_GAP
        depth = previous.depth + 1 if chained and previous is not None else 0
        self._follow[key] = Followup(stamp, depth, bot_text[:400], active=stamp)
        _cap(self._follow, _REACTION_MEMORY)

    def followup(self, channel_id: int, author_id: int) -> tuple[float, Followup] | None:
        found = self._follow.get((channel_id, author_id))
        if found is None:
            return None
        return self.now() - found.opened, found

    def touch_followup(self, channel_id: int, author_id: int) -> bool:
        """La personne écrit ou tape : l'écoute repart, dans la limite de `FOLLOWUP_MAX_S`."""
        found = self._follow.get((channel_id, author_id))
        if found is None or self.now() - found.opened > FOLLOWUP_MAX_S:
            return False
        found.active = self.now()
        return True

    def add_human_reaction(self, message_id: int, emoji: str, user_id: int) -> int:
        users = self._reaction_users.setdefault((message_id, emoji), set())
        users.add(user_id)
        _cap(self._reaction_users, _REACTION_MEMORY)
        return len(users)

    def joined(self, message_id: int, emoji: str) -> bool:
        return (message_id, emoji) in self._joined

    def mark_joined(self, message_id: int, emoji: str) -> None:
        self._joined[(message_id, emoji)] = None
        _cap(self._joined, _REACTION_MEMORY)

    def tracked_reactions(self) -> int:
        return len(self._reaction_users) + len(self._joined)


def _cap[K, V](items: dict[K, V], limit: int) -> None:
    while len(items) > limit:
        items.pop(next(iter(items)))


def _decay(entry: tuple[float, float] | None, now: float, half_life: float) -> float:
    if entry is None:
        return 0.0
    value, stamp = entry
    elapsed = max(0.0, now - stamp)
    return value * 0.5 ** (elapsed / half_life)
