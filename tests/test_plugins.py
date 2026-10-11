"""Extensions : enregistrement annulé au déchargement, et si setup échoue."""

from pathlib import Path

import pytest

from maria_core.app import App
from maria_core.errors import PluginError

_PLUGIN = """\
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk

NAME = "sample"

async def run(ctx: Context, args: Mapping[str, Any]) -> Result:
    return Result(ok=True, data={})

class Ping:
    pass

async def on_ping(event: Ping) -> None:
    on_ping.hits += 1

on_ping.hits = 0

def setup(app: object) -> None:
    app.capabilities.register(
        Capability(
            name="sample_tool",
            description="Outil de test",
            parameters={"type": "object", "properties": {}},
            risk=Risk.READ,
            run=run,
        )
    )
    app.events.subscribe(Ping, on_ping)
    app.prompt.register_section("sample", lambda: "bonjour", order=10)

def teardown(app: object) -> None:
    teardown.calls += 1

teardown.calls = 0
"""

_BROKEN = """\
from maria_core.capabilities import Capability, Context, Result, Risk
from collections.abc import Mapping
from typing import Any

NAME = "broken"

async def run(ctx: Context, args: Mapping[str, Any]) -> Result:
    return Result(ok=True, data={})

def setup(app):
    app.capabilities.register(
        Capability(
            name="broken_tool",
            description="Ne doit pas rester",
            parameters={},
            risk=Risk.READ,
            run=run,
        )
    )
    raise RuntimeError("echec volontaire")
"""


async def test_unload_removes_registrations_and_calls_teardown(app: App, tmp_path: Path) -> None:
    path = tmp_path / "sample_ext.py"
    path.write_text(_PLUGIN, encoding="utf-8")
    assert app.plugins.load_file(path) == "sample"
    module = app.plugins.get_module("sample")

    assert "sample_tool" in app.capabilities
    rendered = app.prompt.render()
    assert rendered.endswith("bonjour")
    assert "MARIA" in rendered
    await app.events.publish(module.Ping())
    assert module.on_ping.hits == 1

    app.plugins.unload("sample")
    assert app.plugins.names == ()
    assert "sample_tool" not in app.capabilities
    assert "bonjour" not in app.prompt.render()
    assert module.teardown.calls == 1

    await app.events.publish(module.Ping())
    assert module.on_ping.hits == 1


def test_failed_setup_rolls_back(app: App, tmp_path: Path) -> None:
    path = tmp_path / "broken_ext.py"
    path.write_text(_BROKEN, encoding="utf-8")
    before = app.capabilities.names()
    with pytest.raises(RuntimeError, match="echec volontaire"):
        app.plugins.load_file(path)
    assert app.plugins.names == ()
    assert app.capabilities.names() == before


def test_reload_keeps_a_single_registration(app: App, tmp_path: Path) -> None:
    path = tmp_path / "sample_ext.py"
    path.write_text(_PLUGIN, encoding="utf-8")
    before = app.capabilities.names()
    app.plugins.load_file(path)
    assert app.plugins.reload("sample") == "sample"
    assert app.capabilities.names() == (*before, "sample_tool")
    assert app.plugins.names == ("sample",)


def test_unknown_extension_is_refused(app: App) -> None:
    with pytest.raises(PluginError, match="introuvable"):
        app.plugins.load("maria_ext_that_does_not_exist")
    with pytest.raises(PluginError, match="inconnue"):
        app.plugins.unload("sample")
