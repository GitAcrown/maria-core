"""Une réponse suit le rythme du salon. Pas de quota fixe."""

from collections import deque
from collections.abc import Hashable
from time import monotonic

WINDOW_S = 600.0


class Pressure:
    def __init__(self) -> None:
        self._authors: dict[Hashable, deque[float]] = {}
        self._channels: dict[Hashable, deque[float]] = {}
        self._follow_authors: dict[Hashable, deque[float]] = {}
        self._follow_channels: dict[Hashable, deque[float]] = {}

    def allow(
        self,
        author_id: int,
        channel_id: int,
        *,
        author_pace: int,
        channel_pace: int,
        followup: bool = False,
    ) -> bool:
        """Autorise tant que les réponses ne dépassent pas les messages déjà vus.

        Le décompte d'une personne est propre à chaque salon, comme ses messages : avoir parlé à
        MARIA ailleurs ne doit pas lui fermer la porte ici.
        """
        if channel_pace <= 0:
            return True
        authors = self._follow_authors if followup else self._authors
        channels = self._follow_channels if followup else self._channels
        now = monotonic()
        mine = (channel_id, author_id)
        if not _within(authors, mine, now, author_pace):
            return False
        if _within(channels, channel_id, now, channel_pace):
            return True
        _give_back(authors, mine)
        return False

    def admit(
        self,
        author_id: int,
        channel_id: int,
        *,
        author_messages: int,
        channel_messages: int,
        limit: str,
        followup: bool,
    ) -> bool:
        """Aucune limite par défaut. Seuls les suivis (MARIA reprend la parole sans qu'on l'appelle)
        sont bridés, à moitié de ce que la personne écrit, et tout le serveur si le réglage le veut.
        """
        if not followup and limit == "none":
            return True
        halve = followup or limit == "strict"
        mine = max(1, author_messages // 2) if halve else author_messages
        room = max(1, channel_messages // 2) if halve and channel_messages else channel_messages
        return self.allow(
            author_id, channel_id, author_pace=mine, channel_pace=room, followup=followup
        )


def _within(buckets: dict[Hashable, deque[float]], key: Hashable, now: float, pace: int) -> bool:
    bucket = buckets.setdefault(key, deque())
    while bucket and now - bucket[0] > WINDOW_S:
        bucket.popleft()
    if not bucket:
        buckets.pop(key, None)
        bucket = buckets.setdefault(key, deque())
    if len(bucket) >= max(pace, 1):
        return False
    bucket.append(now)
    return True


def _give_back(buckets: dict[Hashable, deque[float]], key: Hashable) -> None:
    bucket = buckets.get(key)
    if bucket:
        bucket.pop()
        if not bucket:
            buckets.pop(key, None)
