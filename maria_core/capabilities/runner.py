"""Exécute une capacité : clés, risque, arguments, délai. Toute exception devient un résultat."""

import asyncio
import logging
from datetime import UTC, datetime
from time import perf_counter

from maria_core.capabilities.arguments import prepare_arguments
from maria_core.capabilities.base import Capability, CapabilityRegistry, Context, Result, Risk
from maria_core.capabilities.cache import ResultCache
from maria_core.config import Settings
from maria_core.db import Database
from maria_core.llm.types import ToolCall

logger = logging.getLogger(__name__)

CACHE = ResultCache()

_SETTING_FOR_KEY = {
    "OPENAI_API_KEY": "openai_api_key",
    "TYPESAFE_API_KEY": "typesafe_api_key",
    "BRAVE_API_KEY": "brave_api_key",
    "TMDB_API_KEY": "tmdb_api_key",
    "OPENWEATHERMAP_API_KEY": "openweathermap_api_key",
    "SPOTIFY_CLIENT_ID": "spotify_client_id",
    "SPOTIFY_CLIENT_SECRET": "spotify_client_secret",
    "PRIM_API_KEY": "prim_api_key",
    "SNCF_API_KEY": "sncf_api_key",
    "API_FOOTBALL_KEY": "api_football_key",
}


async def invoke(
    registry: CapabilityRegistry,
    settings: Settings,
    context: Context,
    call: ToolCall,
    *,
    database: Database | None = None,
) -> Result:
    started = perf_counter()
    result = await _invoke(registry, settings, context, call)
    if database is not None:
        elapsed = max(0, int((perf_counter() - started) * 1000))
        await asyncio.to_thread(_log, database, context, call.name, result, elapsed)
    return result


def available(registry: CapabilityRegistry, settings: Settings) -> tuple[Capability, ...]:
    """Capacités utilisables. Le modèle ne voit pas celles dont la clé manque."""
    ready = []
    for name in registry.names():
        capability = registry.get(name)
        if not _missing_keys(settings, capability):
            ready.append(capability)
    return tuple(ready)


async def _invoke(
    registry: CapabilityRegistry,
    settings: Settings,
    context: Context,
    call: ToolCall,
) -> Result:
    if call.name not in registry:
        return Result(ok=False, data={}, error=f"Outil inconnu : {call.name}")
    capability = registry.get(call.name)
    missing = _missing_keys(settings, capability)
    if missing:
        listed = ", ".join(missing)
        return Result(ok=False, data={}, error=f"Capacité indisponible, clé manquante : {listed}")
    denied = _denied(capability, context)
    if denied:
        return Result(ok=False, data={}, error=denied)
    try:
        arguments = prepare_arguments(capability.parameters, dict(call.arguments))
    except ValueError as exc:
        return Result(ok=False, data={}, error=str(exc))
    if capability.cache_s:
        cached = CACHE.get(call.name, arguments)
        if cached is not None:
            return cached
    try:
        result = await asyncio.wait_for(capability.run(context, arguments), capability.timeout_s)
        CACHE.put(call.name, arguments, result, capability.cache_s)
        return result
    except TimeoutError:
        logger.warning("Capacité %s : délai dépassé", call.name)
        return Result(ok=False, data={}, error="Délai dépassé.")
    except Exception as exc:
        logger.exception("Capacité %s en échec", call.name)
        return Result(ok=False, data={}, error=str(exc))


def _denied(capability: Capability, context: Context) -> str:
    """READ, WRITE et EXTERNAL sont ouverts. DANGEROUS est réservé au propriétaire."""
    if capability.risk is Risk.DANGEROUS and not context.is_owner:
        return "Cet outil est réservé au propriétaire du bot."
    return ""


def _missing_keys(settings: Settings, capability: Capability) -> tuple[str, ...]:
    missing = [key for key in sorted(capability.requires) if not _present(settings, key)]
    if capability.requires_any and not any(
        _present(settings, key) for key in capability.requires_any
    ):
        missing.append("une clé parmi " + ", ".join(sorted(capability.requires_any)))
    return tuple(missing)


def _present(settings: Settings, key: str) -> bool:
    attribute = _SETTING_FOR_KEY.get(key)
    if attribute is None:
        return False
    return bool(str(getattr(settings, attribute, "")).strip())


def _log(
    database: Database,
    context: Context,
    name: str,
    result: Result,
    elapsed: int,
) -> None:
    try:
        database.execute(
            """
            INSERT INTO capability_calls (
                at, name, guild_id, user_id, ok, duration_ms, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(UTC).isoformat(),
                name[:80],
                context.guild_id,
                context.user_id,
                1 if result.ok else 0,
                elapsed,
                result.error[:300],
            ),
        )
    except Exception:
        logger.exception("Journal de capacité impossible pour %s", name)
