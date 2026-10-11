"""Fixtures communes. Chaque test ouvre sa base dans un dossier temporaire."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from maria_core.app import App
from maria_core.config import Settings


@pytest.fixture
def app(tmp_path: Path) -> Iterator[App]:
    opened = App.open(Settings.for_tests(tmp_path / "data"))
    try:
        yield opened
    finally:
        opened.close()
