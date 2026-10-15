"""Réglages lus une fois au démarrage. Rien n'est lu au moment de l'import."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from maria_core.errors import ConfigError

_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
DEFAULT_PLUGINS = (
    "maria_core.plugins.weather",
    "maria_core.plugins.football",
    "maria_core.plugins.tmdb",
    "maria_core.plugins.youtube",
    "maria_core.plugins.spotify",
    "maria_core.plugins.steam",
    "maria_core.plugins.transport",
    # Halloween 2026 (jusqu'au 1er novembre) : retrait pas à pas dans RETRAIT_HALLOWEEN.md.
    # L'outil s'éteint seul après le 1er novembre.
    "maria_core.plugins.halloween",
)


def _optional_int(raw: str, name: str) -> int | None:
    text = raw.strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError as exc:
        raise ConfigError(f"{name} doit être un entier.") from exc
    if value <= 0:
        raise ConfigError(f"{name} doit être un entier positif.")
    return value


def _plugins(source: Mapping[str, str]) -> tuple[str, ...]:
    """Clé absente : les extensions médias. Clé vide : aucune."""
    if "PLUGINS" not in source:
        return DEFAULT_PLUGINS
    return _csv(source.get("PLUGINS", ""))


def _csv(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _environ_from_dotenv(env_file: Path | None) -> Mapping[str, str]:
    if env_file is not None:
        if not env_file.is_file():
            raise ConfigError(f"Fichier d'environnement introuvable : {env_file}")
        load_dotenv(env_file, override=False)
    else:
        candidate = Path.cwd() / ".env"
        if candidate.is_file():
            load_dotenv(candidate, override=False)
    return os.environ


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuration du processus. Les clés de capacités sont vides si absentes."""

    token: str
    app_id: int | None
    openai_api_key: str
    typesafe_api_key: str
    brave_api_key: str
    tmdb_api_key: str
    openweathermap_api_key: str
    spotify_client_id: str
    spotify_client_secret: str
    prim_api_key: str
    sncf_api_key: str
    api_football_key: str
    data_dir: Path
    command_prefix: str
    log_level: str
    plugins: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.log_level not in _LEVELS:
            raise ConfigError(
                f"LOG_LEVEL invalide : {self.log_level!r}. Attendu : {', '.join(sorted(_LEVELS))}."
            )
        if not self.command_prefix:
            raise ConfigError("COMMAND_PREFIX est vide.")
        object.__setattr__(self, "data_dir", Path(self.data_dir).expanduser().resolve())

    @property
    def database_path(self) -> Path:
        return self.data_dir / "maria.db"

    def require_bot(self) -> None:
        """Exige les clés sans lesquelles le bot ne peut pas se connecter."""
        missing = [
            name
            for name, present in (
                ("TOKEN", bool(self.token)),
                ("APP_ID", self.app_id is not None),
                ("OPENAI_API_KEY", bool(self.openai_api_key)),
            )
            if not present
        ]
        if missing:
            raise ConfigError("Variable(s) manquante(s) : " + ", ".join(missing))

    @classmethod
    def load(
        cls,
        *,
        env_file: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> Settings:
        """Construit les réglages. `environ` court-circuite le fichier `.env` (tests)."""
        source = environ if environ is not None else _environ_from_dotenv(env_file)
        return cls(
            token=source.get("TOKEN", "").strip(),
            app_id=_optional_int(source.get("APP_ID", ""), "APP_ID"),
            openai_api_key=source.get("OPENAI_API_KEY", "").strip(),
            typesafe_api_key=source.get("TYPESAFE_API_KEY", "").strip(),
            brave_api_key=source.get("BRAVE_API_KEY", "").strip(),
            tmdb_api_key=source.get("TMDB_API_KEY", "").strip(),
            openweathermap_api_key=source.get("OPENWEATHERMAP_API_KEY", "").strip(),
            spotify_client_id=source.get("SPOTIFY_CLIENT_ID", "").strip(),
            spotify_client_secret=source.get("SPOTIFY_CLIENT_SECRET", "").strip(),
            prim_api_key=source.get("PRIM_API_KEY", "").strip(),
            sncf_api_key=source.get("SNCF_API_KEY", "").strip(),
            api_football_key=source.get("API_FOOTBALL_KEY", "").strip(),
            data_dir=Path(source.get("DATA_DIR", "data").strip() or "data"),
            command_prefix=source.get("COMMAND_PREFIX", "5!").strip(),
            log_level=(source.get("LOG_LEVEL", "INFO").strip() or "INFO").upper(),
            plugins=_plugins(source),
        )

    @classmethod
    def for_tests(cls, data_dir: Path) -> Settings:
        """Réglages vides, base isolée. Aucune clé n'est lue dans l'environnement."""
        return cls(
            token="",
            app_id=None,
            openai_api_key="",
            typesafe_api_key="",
            brave_api_key="",
            tmdb_api_key="",
            openweathermap_api_key="",
            spotify_client_id="",
            spotify_client_secret="",
            prim_api_key="",
            sncf_api_key="",
            api_football_key="",
            data_dir=data_dir,
            command_prefix="5!",
            log_level="INFO",
            plugins=(),
        )
