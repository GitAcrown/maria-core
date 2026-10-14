"""Relie le stockage, le moteur et l'horloge. Discord branche le courrier plus tard."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from maria_core.db import Database
from maria_core.objectives.catalog import register_builtin_kinds
from maria_core.objectives.matcher import Matcher
from maria_core.objectives.pipeline import Fetcher, Judge, Writer
from maria_core.objectives.runner import Runner
from maria_core.objectives.scheduler import Scheduler
from maria_core.objectives.signals import ObjectiveSignal
from maria_core.objectives.store import ObjectiveStore
from maria_core.objectives.types import ObjectiveTypes

type Clock = Callable[[], datetime]


class Objectives:
    """Point d'accroche des extensions : `app.objectives.types`."""

    def __init__(
        self,
        database: Database,
        *,
        clock: Clock | None = None,
        fetcher: Fetcher | None = None,
        writer: Writer | None = None,
        judge: Judge | None = None,
    ) -> None:
        self.types = ObjectiveTypes()
        register_builtin_kinds(self.types)
        self.store = ObjectiveStore(database)
        self._clock = clock or _now
        self.runner = Runner(
            self.store,
            database,
            clock=self._clock,
            fetcher=fetcher,
            writer=writer,
            judge=judge,
        )
        self.matcher = Matcher(self.store, self.runner)
        self.is_request: Callable[[str], Awaitable[bool]] | None = None
        self.scheduler = Scheduler(self.store, self.runner, clock=self._clock)

    @property
    def pipeline(self):
        return self.runner.pipeline

    def now(self) -> datetime:
        return self._clock()

    async def on_signal(self, signal: object) -> None:
        if isinstance(signal, ObjectiveSignal):
            await self.matcher.handle(signal, now=self.now())


def _now() -> datetime:
    return datetime.now(UTC)
