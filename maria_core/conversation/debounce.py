"""Un seul tour par auteur et par salon, le dernier message gagne."""

import asyncio
from collections.abc import Awaitable, Callable

from maria_core.conversation.model import Inbound

type Sleeper = Callable[[float], Awaitable[None]]


class Debouncer:
    def __init__(self, delay: float, *, sleep: Sleeper = asyncio.sleep) -> None:
        self._delay = delay
        self._sleep = sleep
        self._latest: dict[tuple[int, int], Inbound] = {}

    async def submit(self, message: Inbound) -> Inbound | None:
        """Attend, puis rend le dernier message du créneau.

        Les appels suivants pendant l'attente rendent `None` : le premier
        en attente repart avec la version la plus récente.
        """
        key = (message.channel_id, message.author_id)
        waiting = key in self._latest
        self._latest[key] = message
        if waiting:
            return None
        try:
            await self._sleep(self._delay)
        finally:
            latest = self._latest.pop(key, None)
        return latest

    def __len__(self) -> int:
        return len(self._latest)
