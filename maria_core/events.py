"""Bus interne. Les adaptateurs Discord publient, le métier s'abonne."""

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from maria_core.errors import RegistryError
from maria_core.ledger import note_undo

logger = logging.getLogger(__name__)

type Handler = Callable[..., Awaitable[None]]


class EventBus:
    """Distribution en ordre de spécificité : la sous-classe avant la classe de base."""

    def __init__(self) -> None:
        self._handlers: dict[type[object], list[Handler]] = defaultdict(list)
        self._pending: set[asyncio.Task[int]] = set()

    def subscribe(self, event_type: type[object], handler: Handler) -> None:
        if not inspect.iscoroutinefunction(handler):
            raise RegistryError("Le gestionnaire d'événement doit être une coroutine.")
        handlers = self._handlers[event_type]
        if handler in handlers:
            raise RegistryError(f"Gestionnaire déjà abonné à {event_type.__name__}.")
        handlers.append(handler)
        note_undo(lambda kind=event_type, callback=handler: self._discard(kind, callback))

    def unsubscribe(self, event_type: type[object], handler: Handler) -> None:
        if handler not in self._handlers.get(event_type, []):
            raise RegistryError(f"Gestionnaire inconnu pour {event_type.__name__}.")
        self._discard(event_type, handler)

    async def publish(self, event: object) -> int:
        """Appelle les abonnés. Une erreur est journalisée et n'arrête pas les autres.

        Renvoie le nombre de gestionnaires qui ont levé.
        """
        failures = 0
        for handler in self._matching(event):
            try:
                await handler(event)
            except Exception:
                failures += 1
                logger.exception(
                    "Gestionnaire %s en échec pour %s",
                    getattr(handler, "__name__", handler),
                    type(event).__name__,
                )
        return failures

    def publish_soon(self, event: object) -> asyncio.Task[int]:
        """Publie en tâche de fond : l'appelant n'attend pas les abonnés."""
        task = asyncio.create_task(self.publish(event))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return task

    def _matching(self, event: object) -> list[Handler]:
        found: list[Handler] = []
        for cls in type(event).mro():
            if cls is object:
                break
            found.extend(self._handlers.get(cls, ()))
        return found

    def _discard(self, event_type: type[object], handler: Handler) -> None:
        handlers = self._handlers.get(event_type)
        if not handlers or handler not in handlers:
            return
        handlers.remove(handler)
        if not handlers:
            self._handlers.pop(event_type, None)
