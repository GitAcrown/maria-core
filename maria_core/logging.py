"""Journal clé=valeur. Les bibliothèques restent au niveau WARNING."""

import logging
import sys
from logging.handlers import RotatingFileHandler

from maria_core.config import Settings

_STREAM = "maria-core-stream"
_FILE = "maria-core-file"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUPS = 3


class KeyValueFormatter(logging.Formatter):
    """Une ligne : ts=… level=… logger=… msg=…"""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, "%Y-%m-%dT%H:%M:%S")
        parts = [
            f"ts={timestamp}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"msg={_quote(record.getMessage())}",
        ]
        if record.exc_info:
            trace = self.formatException(record.exc_info).replace("\n", " | ")
            parts.append(f"exc={_quote(trace)}")
        return " ".join(parts)


class _LibraryFilter(logging.Filter):
    """Le paquet parle au niveau demandé. Le reste, à partir de WARNING."""

    def __init__(self, package_level: int) -> None:
        super().__init__()
        self._package_level = package_level

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith("maria_core"):
            return record.levelno >= self._package_level
        return record.levelno >= logging.WARNING


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    if escaped == "" or any(character.isspace() or character in '=|"' for character in escaped):
        return f'"{escaped}"'
    return escaped


def _handler(name: str, settings: Settings, package_level: int) -> logging.Handler:
    if name == _STREAM:
        handler: logging.Handler = logging.StreamHandler(sys.stdout)
    else:
        log_dir = settings.data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "maria.log",
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUPS,
            encoding="utf-8",
        )
    handler.name = name
    handler.setFormatter(KeyValueFormatter())
    handler.addFilter(_LibraryFilter(package_level))
    return handler


def configure_logging(settings: Settings) -> None:
    """Branche le journal du processus. Appel idempotent."""
    root = logging.getLogger()
    package_level = logging.getLevelNamesMapping()[settings.log_level]
    logging.getLogger("maria_core").setLevel(package_level)
    # isEnabledFor remonte au root. On l'abaisse, et le filtre trie
    # les bibliothèques pour que leurs INFO n'apparaissent pas.
    if root.level == logging.NOTSET or root.level > logging.DEBUG:
        root.setLevel(logging.DEBUG)
    names = {handler.name for handler in root.handlers}
    if _STREAM not in names:
        root.addHandler(_handler(_STREAM, settings, package_level))
    if _FILE not in names:
        root.addHandler(_handler(_FILE, settings, package_level))
