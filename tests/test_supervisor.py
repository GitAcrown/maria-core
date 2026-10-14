"""Relance après plantage : attente croissante, arrêts voulus respectés, signal d'arrêt obéi."""

import sys
import threading
from collections.abc import Mapping, Sequence

from maria_core.supervisor import CHILD_ENV, RESTARTS_ENV, Backoff, supervise


class _Child:
    def __init__(self, code: int) -> None:
        self.code = code
        self.terminated = False

    def wait(self, timeout: float | None = None) -> int:
        return self.code

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


class _Launcher:
    """Lance des faux fils qui se terminent avec les codes donnés, dans l'ordre."""

    def __init__(self, codes: list[int]) -> None:
        self.codes = list(codes)
        self.environments: list[Mapping[str, str]] = []

    def __call__(self, command: Sequence[str], environ: Mapping[str, str]) -> _Child:
        self.environments.append(environ)
        return _Child(self.codes.pop(0))


class _Clock:
    """Chaque lancement dure `runs[i]` secondes."""

    def __init__(self, runs: list[float]) -> None:
        self.runs = list(runs)
        self.now = 0.0
        self.starting = True

    def __call__(self) -> float:
        if self.starting:
            self.starting = False
        else:
            self.now += self.runs.pop(0)
            self.starting = True
        return self.now


def test_the_wait_doubles_and_is_capped() -> None:
    plan = Backoff()
    assert [plan.delay(n) for n in range(1, 10)] == [5, 10, 20, 40, 80, 160, 320, 640, 900]
    assert Backoff(first=1, factor=3, cap=20).delay(4) == 20


class _Pauses(threading.Event):
    """Un arrêt qui note les attentes demandées au lieu de dormir."""

    def __init__(self) -> None:
        super().__init__()
        self.waits: list[float] = []

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(float(timeout or 0))
        return self.is_set()


def test_a_crash_is_restarted_with_a_growing_wait_until_a_clean_stop() -> None:
    launcher = _Launcher([1, -9, 1, 0])
    stop = _Pauses()
    code = supervise(
        ["python", "-m", "maria_core"],
        spawn=launcher,
        stop=stop,
        clock=_Clock([3, 3, 3, 3]),
        say=lambda _line: None,
        environ={"TOKEN": "x"},
    )
    assert code == 0 and not launcher.codes
    assert stop.waits == [5, 10, 20]
    assert [env[RESTARTS_ENV] for env in launcher.environments] == ["0", "1", "2", "3"]
    assert all(env[CHILD_ENV] == "1" and env["TOKEN"] == "x" for env in launcher.environments)


def test_a_wrong_configuration_or_a_clean_stop_is_never_retried() -> None:
    for code in (0, 2):
        launcher = _Launcher([code, 1])
        result = supervise(["x"], spawn=launcher, say=lambda _line: None)
        assert result == code and launcher.codes == [1]


def test_a_long_run_starts_the_wait_over() -> None:
    launcher = _Launcher([1, 1, 1, 1, 0])
    stop = _Pauses()
    clock = _Clock([5, 5, 700, 5])  # le troisième fils a tenu 700 s : on repart de 5 s
    supervise(["x"], spawn=launcher, stop=stop, clock=clock, say=lambda _line: None)
    assert stop.waits == [5, 10, 5, 10]


def test_a_stop_request_ends_everything_without_another_attempt() -> None:
    stop = threading.Event()
    launcher = _Launcher([1, 0])

    def listen(_line: str) -> None:
        stop.set()

    result = supervise(["x"], spawn=launcher, stop=stop, say=listen)
    assert result == 0 and launcher.codes == [0]


def test_a_real_process_is_restarted_then_left_alone() -> None:
    script = "import os, sys; sys.exit(1 if os.environ['MARIA_RESTARTS'] == '0' else 0)"
    said: list[str] = []
    code = supervise(
        [sys.executable, "-c", script],
        backoff=Backoff(first=0.01, cap=0.02),
        say=said.append,
    )
    assert code == 0 and len(said) == 1 and "n°1" in said[0]
