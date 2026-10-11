"""Démarre le processus. `python -m maria_core` ou la commande `maria`."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from maria_core import __version__
from maria_core.app import App
from maria_core.config import Settings
from maria_core.discord.bot import MariaBot
from maria_core.errors import ConfigError, MariaError
from maria_core.logging import configure_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maria")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Ouvre la base et charge les extensions, sans se connecter à Discord.",
    )
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        settings = Settings.load(env_file=args.env_file)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    configure_logging(settings)
    try:
        if args.check:
            _check(settings)
            return 0
        settings.require_bot()
        asyncio.run(_serve(settings))
    except KeyboardInterrupt:
        return 0
    except MariaError as exc:
        logger.exception("Démarrage impossible")
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def _check(settings: Settings) -> None:
    app = App.open(settings)
    try:
        names = ", ".join(app.plugins.names) or "aucune"
        print(
            f"maria-core {__version__} — base v{app.database.version} — extensions : {names}",
            flush=True,
        )
    finally:
        app.close()


async def _serve(settings: Settings) -> None:
    app = App.open(settings)
    bot = MariaBot(app)
    try:
        async with bot:
            await bot.start(settings.token)
    finally:
        await app.aclose()


if __name__ == "__main__":
    sys.exit(main())
