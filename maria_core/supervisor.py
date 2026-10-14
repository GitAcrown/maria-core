"""Relance le bot s'il plante, avec une attente qui double d'une tentative à l'autre.

Le parent ne fait que surveiller : il lance `python -m maria_core` comme processus fils et regarde
comment il se termine. Arrêt voulu (code 0) ou configuration à corriger (code 2) : il s'arrête
aussi, rien ne sert d'insister. Tout le reste (exception, signal, mémoire épuisée) est relancé.
"""

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Protocol

CHILD_ENV = "MARIA_SUPERVISED"
RESTARTS_ENV = "MARIA_RESTARTS"
STOP_CODES = frozenset({0, 2})
_GRACE_S = 20.0


@dataclass(frozen=True, slots=True)
class Backoff:
    """5 s, 10 s, 20 s… jusqu'à 15 min. Un fils resté en vie 10 min repart de zéro."""

    first: float = 5.0
    factor: float = 2.0
    cap: float = 900.0
    stable: float = 600.0

    def delay(self, failures: int) -> float:
        return min(self.cap, self.first * self.factor ** max(0, failures - 1))


class Child(Protocol):
    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


type Spawn = Callable[[Sequence[str], Mapping[str, str]], Child]
type Say = Callable[[str], None]


def supervise(
    command: Sequence[str],
    *,
    backoff: Backoff | None = None,
    spawn: Spawn | None = None,
    stop: threading.Event | None = None,
    clock: Callable[[], float] = time.monotonic,
    say: Say | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Code de sortie du dernier fils. `stop` (signal reçu) arrête tout proprement."""
    plan = backoff or Backoff()
    halt = stop or threading.Event()
    launch = spawn or _spawn
    tell = say or _say
    base = dict(os.environ if environ is None else environ)
    failures = restarts = 0
    while True:
        started = clock()
        child = launch(command, {**base, CHILD_ENV: "1", RESTARTS_ENV: str(restarts)})
        code = _wait(child, halt)
        if halt.is_set() or code in STOP_CODES:
            return 0 if halt.is_set() else code
        ran = clock() - started
        failures = 1 if ran >= plan.stable else failures + 1
        pause = plan.delay(failures)
        restarts += 1
        tell(
            f"Le bot s'est arrêté (code {code}) après {ran:.0f} s. "
            f"Nouvelle tentative n°{restarts} dans {pause:.0f} s."
        )
        if halt.wait(pause):
            return 0


def _wait(child: Child, halt: threading.Event) -> int:
    """Attend le fils ; si un arrêt est demandé, lui laisse 20 s pour se fermer proprement."""
    while True:
        try:
            return child.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            if halt.is_set():
                return _stop(child)


def _stop(child: Child) -> int:
    child.terminate()
    try:
        return child.wait(timeout=_GRACE_S)
    except subprocess.TimeoutExpired:
        child.kill()
        return child.wait()


def run(command: Sequence[str]) -> int:
    """Branche les signaux d'arrêt (Ctrl+C, SIGTERM) sur la boucle de relance."""
    halt = threading.Event()

    def on_signal(_signum: int, _frame: FrameType | None) -> None:
        halt.set()

    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), on_signal)
    return supervise(command, stop=halt)


def child_command(argv: Sequence[str]) -> list[str]:
    return [sys.executable, "-m", "maria_core", *argv]


def project_root() -> str:
    return str(Path(__file__).resolve().parents[1])


def is_child() -> bool:
    return os.environ.get(CHILD_ENV) == "1"


def _spawn(command: Sequence[str], environ: Mapping[str, str]) -> Child:
    """Le fils retrouve le paquet même si le parent a été lancé d'un autre dossier."""
    env = dict(environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [project_root(), env.get("PYTHONPATH", "")]))
    return subprocess.Popen(list(command), env=env)


def _say(message: str) -> None:
    print(f"[supervision] {message}", file=sys.stderr, flush=True)
