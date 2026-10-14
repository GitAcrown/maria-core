"""Une réponse suit le rythme du salon. Pas de quota fixe."""

from collections import deque
from collections.abc import Hashable
from time import monotonic

WINDOW_S = 600.0


class Pressure:
    def __init__(self) -> None:
        self._authors: dict[Hashable, deque[float]] = {}
        self._channels: dict[Hashable, deque[float]] = {}

    def allow(
        self,
        author_id: int,
        channel_id: int,
        *,
        author_pace: int,
        channel_pace: int,
    ) -> bool:
        """Autorise tant que les réponses ne dépassent pas les messages déjà vus.

        Le décompte d'une personne est propre à chaque salon, comme ses messages : avoir parlé à
        MARIA ailleurs ne doit pas lui fermer la porte ici.
        """
        if channel_pace <= 0:
            return True
        now = monotonic()
        mine = (channel_id, author_id)
        if not _within(self._authors, mine, now, author_pace):
            return False
        if _within(self._channels, channel_id, now, channel_pace):
            return True
        _give_back(self._authors, mine)
        return False


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
