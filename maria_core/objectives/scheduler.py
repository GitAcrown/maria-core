"""Boucle : réserve un objectif dû, l'exécute, recommence."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from maria_core.objectives.runner import Runner
from maria_core.objectives.store import ObjectiveStore

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        store: ObjectiveStore,
        runner: Runner,
        *,
        interval: float = 5.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._runner = runner
        self._interval = interval
        self._clock = clock or _now
        self._stopped = asyncio.Event()

    def stop(self) -> None:
        self._stopped.set()

    async def run(self) -> None:
        while not self._stopped.is_set():
            worked = await self._safe_tick()
            if worked:
                continue
            try:
                await asyncio.wait_for(self._stopped.wait(), self._interval)
            except TimeoutError:
                continue

    async def tick(self) -> bool:
        claimed = await asyncio.to_thread(self._store.claim, self._clock())
        if claimed is None:
            return False
        await self._runner.execute(claimed)
        return True

    async def _safe_tick(self) -> bool:
        try:
            return await self.tick()
        except Exception:
            logger.exception("Tour d'objectifs en échec")
            return False


def _now() -> datetime:
    return datetime.now(UTC)
