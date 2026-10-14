"""Démarre le processus. `python -m maria_core` ou la commande `maria`."""

import os
import sys

if not __package__:
    # Lancé comme un fichier (`python maria_core` ou `python maria_core/__main__.py`) : Python met
    # alors ce dossier en tête de sys.path, et nos modules (discord, profile…) masqueraient la
    # bibliothèque standard et discord.py. On l'écarte et on prend le dossier du projet.
    _HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [item for item in sys.path if os.path.abspath(item or os.curdir) != _HERE]
    sys.path.insert(0, os.path.dirname(_HERE))

import argparse
import asyncio
import logging
from pathlib import Path

from maria_core import __version__, supervisor
from maria_core.app import App
from maria_core.config import Settings
from maria_core.discord.bot import MariaBot, fatal_errors
from maria_core.errors import ConfigError, MariaError
from maria_core.journal import configure_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maria")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Ouvre la base et charge les extensions, sans se connecter à Discord.",
    )
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Ne relance pas le bot après un plantage (par exemple si systemd s'en charge).",
    )
    args = parser.parse_args(argv)
    if not (args.check or args.no_restart or supervisor.is_child()):
        return supervisor.run(supervisor.child_command(argv if argv is not None else sys.argv[1:]))
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
    except ConfigError as exc:
        logger.error("Configuration invalide : %s", exc)
        print(str(exc), file=sys.stderr)
        return 2
    except MariaError as exc:
        logger.exception("Démarrage impossible")
        print(str(exc), file=sys.stderr)
        return 1
    except fatal_errors() as exc:
        logger.error("Discord refuse la connexion : %s", exc)
        print(
            f"Discord refuse la connexion ({exc}) : vérifie TOKEN et les intents.", file=sys.stderr
        )
        return 2
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
