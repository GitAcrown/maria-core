"""Réglages : valeurs par défaut, refus, absence de lecture surprise."""

from pathlib import Path

import pytest

from maria_core.config import Settings
from maria_core.errors import ConfigError


def test_load_reads_the_mapping_not_the_process_environment(tmp_path: Path) -> None:
    settings = Settings.load(
        environ={
            "TOKEN": " secret ",
            "APP_ID": "42",
            "OPENAI_API_KEY": "sk",
            "DATA_DIR": str(tmp_path),
            "LOG_LEVEL": "debug",
            "PLUGINS": "alpha, beta",
        }
    )
    assert settings.token == "secret"
    assert settings.app_id == 42
    assert settings.log_level == "DEBUG"
    assert settings.plugins == ("alpha", "beta")
    assert settings.data_dir == tmp_path.resolve()


def test_plugins_default_to_the_media_pack() -> None:
    settings = Settings.load(environ={})
    assert "maria_core.plugins.weather" in settings.plugins
    assert Settings.load(environ={"PLUGINS": ""}).plugins == ()


def test_missing_bot_keys_are_named() -> None:
    settings = Settings.for_tests(Path("data"))
    with pytest.raises(ConfigError, match="TOKEN"):
        settings.require_bot()


def test_app_id_must_be_a_positive_integer() -> None:
    with pytest.raises(ConfigError, match="APP_ID"):
        Settings.load(environ={"APP_ID": "abc"})
    with pytest.raises(ConfigError, match="APP_ID"):
        Settings.load(environ={"APP_ID": "0"})


def test_unknown_log_level_is_refused() -> None:
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        Settings.load(environ={"LOG_LEVEL": "verbose"})


def test_missing_env_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="introuvable"):
        Settings.load(env_file=tmp_path / "absent.env")
