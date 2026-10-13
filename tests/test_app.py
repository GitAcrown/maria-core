"""Démarrage : base migrée, fermeture idempotente, vérification sans token."""

import sqlite3
from dataclasses import replace
from pathlib import Path

from maria_core.__main__ import main
from maria_core.app import App
from maria_core.config import Settings


def test_open_migrates_and_close_is_idempotent(app: App) -> None:
    assert app.database.version == 13
    app.close()
    app.close()


def test_a_broken_plugin_does_not_stop_the_process(tmp_path: Path) -> None:
    settings = replace(Settings.for_tests(tmp_path / "data"), plugins=("maria_missing_plugin",))
    opened = App.open(settings)
    try:
        assert opened.plugins.names == ()
        assert opened.database.version == 13
    finally:
        opened.close()


def test_configured_plugin_is_loaded(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "plugsrc"
    source.mkdir()
    (source / "demo_ext.py").write_text(
        "\n".join(
            [
                "NAME = 'demo'",
                "def setup(app):",
                "    app.prompt.register_section('demo', lambda: 'présent')",
                "def teardown(app):",
                "    teardown.done = True",
                "teardown.done = False",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(source))
    settings = replace(Settings.for_tests(tmp_path / "data"), plugins=("demo_ext",))
    opened = App.open(settings)
    try:
        assert opened.plugins.names == ("demo",)
        assert "présent" in opened.prompt.render()
    finally:
        opened.close()
    assert opened.plugins.names == ()


def test_check_command_migrates_without_a_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    for key in ("TOKEN", "APP_ID", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert main(["--check"]) == 0
    connection = sqlite3.connect(tmp_path / "data" / "maria.db")
    try:
        version = connection.execute("PRAGMA user_version").fetchone()
    finally:
        connection.close()
    assert version is not None
    assert version[0] == 13
