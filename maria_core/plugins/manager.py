"""Chargement des extensions. `setup` enregistre, le ledger annule au déchargement."""

import importlib
import importlib.util
import logging
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Protocol

from maria_core.capabilities import CapabilityRegistry
from maria_core.capabilities.http import HttpClient
from maria_core.commands import CommandCatalog
from maria_core.config import Settings
from maria_core.db import Database
from maria_core.decisions import DecisionRegistry
from maria_core.errors import PluginError, RegistryError
from maria_core.events import EventBus
from maria_core.ledger import Ledger, tracking
from maria_core.llm import PromptSections
from maria_core.names import require_name
from maria_core.objectives import Objectives
from maria_core.ui import WidgetRegistry

logger = logging.getLogger(__name__)


class PluginHost(Protocol):
    """Attributs qu'une extension est autorisée à utiliser. `App` les fournit."""

    settings: Settings
    database: Database
    http: HttpClient
    capabilities: CapabilityRegistry
    widgets: WidgetRegistry
    decisions: DecisionRegistry
    objectives: Objectives
    prompt: PromptSections
    commands: CommandCatalog
    events: EventBus


@dataclass(slots=True)
class _Loaded:
    name: str
    module_name: str
    origin: Path | None
    teardown: Callable[[PluginHost], None] | None
    ledger: Ledger


class PluginManager:
    def __init__(self, host: PluginHost) -> None:
        self._host = host
        self._plugins: dict[str, _Loaded] = {}
        self._order: list[str] = []

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._order)

    def load(self, module_name: str) -> str:
        """Charge un module importable (`PLUGINS` ou commande owner)."""
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            raise PluginError(f"Extension introuvable : {module_name}") from exc
        return self._activate(module, origin=None)

    def load_file(self, path: Path) -> str:
        """Charge un fichier. Utilisé par les tests et un rechargement local."""
        module_name = _synthetic_name(path)
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise PluginError(f"Fichier d'extension illisible : {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            return self._activate(module, origin=path.resolve())
        except Exception:
            sys.modules.pop(module_name, None)
            raise

    def unload(self, name: str) -> None:
        plugin = self._require(name)
        try:
            if plugin.teardown is not None:
                plugin.teardown(self._host)
        finally:
            plugin.ledger.rollback()
            self._order.remove(name)
            self._plugins.pop(name, None)
            if plugin.origin is not None:
                sys.modules.pop(plugin.module_name, None)
        logger.info("Extension déchargée : %s", name)

    def get_module(self, name: str) -> ModuleType:
        plugin = self._require(name)
        module = sys.modules.get(plugin.module_name)
        if module is None:
            raise PluginError(f"Module introuvable pour l'extension {name}.")
        return module

    def reload(self, name: str) -> str:
        plugin = self._require(name)
        origin = plugin.origin
        module_name = plugin.module_name
        self.unload(name)
        if origin is not None:
            return self.load_file(origin)
        sys.modules.pop(module_name, None)
        return self.load(module_name)

    def unload_all(self) -> None:
        for name in reversed(list(self._order)):
            self.unload(name)

    def _activate(self, module: ModuleType, *, origin: Path | None) -> str:
        name = _read_name(module)
        if name in self._plugins:
            raise PluginError(f"Extension déjà chargée : {name}")
        setup = _callable(module, "setup")
        teardown = _optional_callable(module, "teardown")
        with tracking() as ledger:
            try:
                setup(self._host)
            except Exception:
                ledger.rollback()
                raise
        self._plugins[name] = _Loaded(name, module.__name__, origin, teardown, ledger)
        self._order.append(name)
        logger.info("Extension chargée : %s", name)
        return name

    def _require(self, name: str) -> _Loaded:
        try:
            return self._plugins[name]
        except KeyError as exc:
            raise PluginError(f"Extension inconnue : {name}") from exc


def _synthetic_name(path: Path) -> str:
    stem = "".join(character if character.isalnum() else "_" for character in path.stem.lower())
    return f"maria_ext_{stem}_{uuid.uuid4().hex}"


def _read_name(module: ModuleType) -> str:
    raw = getattr(module, "NAME", None)
    if not isinstance(raw, str):
        raise PluginError(f"{module.__name__} doit définir NAME.")
    try:
        return require_name(raw, what="Nom d'extension")
    except RegistryError as exc:
        raise PluginError(str(exc)) from exc


def _callable(module: ModuleType, attribute: str) -> Callable[[PluginHost], None]:
    value = getattr(module, attribute, None)
    if not callable(value):
        raise PluginError(f"{module.__name__} doit définir {attribute}(app).")
    return value


def _optional_callable(
    module: ModuleType,
    attribute: str,
) -> Callable[[PluginHost], None] | None:
    value = getattr(module, attribute, None)
    if value is None:
        return None
    if not callable(value):
        raise PluginError(f"{module.__name__}.{attribute} doit être appelable.")
    return value
