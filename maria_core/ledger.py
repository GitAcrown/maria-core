"""Annule les enregistrements faits pendant le chargement d'une extension."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar


class Ledger:
    """Pile d'annulations, exécutée à l'envers au déchargement."""

    def __init__(self) -> None:
        self._undo: list[Callable[[], None]] = []

    def add(self, undo: Callable[[], None]) -> None:
        self._undo.append(undo)

    def rollback(self) -> None:
        while self._undo:
            self._undo.pop()()


_current: ContextVar[Ledger | None] = ContextVar("maria_plugin_ledger", default=None)


def note_undo(undo: Callable[[], None]) -> None:
    """Mémorise une annulation si un chargement d'extension est en cours."""
    ledger = _current.get()
    if ledger is not None:
        ledger.add(undo)


@contextmanager
def tracking() -> Iterator[Ledger]:
    """Ouvre un registre d'annulation pour la durée d'un `setup`."""
    ledger = Ledger()
    token = _current.set(ledger)
    try:
        yield ledger
    finally:
        _current.reset(token)
