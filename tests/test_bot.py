"""L'adaptateur Discord se construit sans ouvrir de connexion."""

from pathlib import Path

from maria_core.app import App
from maria_core.config import Settings
from maria_core.discord.bot import MariaBot, build_intents


def test_intents_include_the_privileged_ones() -> None:
    intents = build_intents()
    assert intents.message_content
    assert intents.members
    assert intents.voice_states


def test_bot_keeps_the_configured_prefix(tmp_path: Path) -> None:
    app = App.open(Settings.for_tests(tmp_path / "data"))
    try:
        bot = MariaBot(app)
        assert bot.command_prefix == "5!"
        assert bot.app is app
    finally:
        app.close()
