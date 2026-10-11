"""run_python : propriétaire seulement, et serveur explicitement activé."""

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from maria_core.capabilities.base import Capability, Context, Result, Risk
from maria_core.db import Database

_TIMEOUT = 4


def python_capability(database: Database) -> Capability:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        if context.guild_id is not None:
            enabled = await asyncio.to_thread(_enabled, database, context.guild_id)
            if not enabled:
                return Result(ok=False, data={}, error="Python est désactivé sur ce serveur.")
        payload = await asyncio.to_thread(_isolated, str(args.get("code") or ""))
        if "error" in payload:
            return Result(ok=False, data=payload, error=str(payload["error"]))
        return Result(ok=True, data=payload)

    return Capability(
        name="run_python",
        description=(
            "Exécute un court programme Python (math, statistics, datetime, decimal, json, re). "
            "print() et la dernière expression sont renvoyés. "
            "Pas de fichiers, pas de réseau, pas d'import, 4 secondes. "
            "Réservé au propriétaire, et désactivé sur un serveur tant que python_enabled vaut 0."
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Expression ou petit script Python"},
            },
            "required": ["code"],
        },
        risk=Risk.DANGEROUS,
        run=run,
        timeout_s=8,
    )


def _enabled(database: Database, guild_id: int) -> bool:
    row = database.fetchone(
        "SELECT python_enabled FROM guild_settings WHERE guild_id = ?",
        (guild_id,),
    )
    return row is not None and int(row["python_enabled"]) == 1


def _isolated(code: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "maria_core.capabilities.builtin.sandbox"],
            input=code.encode("utf-8"),
            capture_output=True,
            timeout=_TIMEOUT,
            cwd=os.environ.get("TEMP") or os.environ.get("TMP") or ".",
            env=_env(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"error": "Exécution trop longue", "hint": "Simplifie le calcul."}
    except OSError as exc:
        return {"error": f"Sandbox indisponible : {exc}"}
    return _decode(completed.stdout, completed.stderr, completed.returncode)


def _decode(stdout: bytes, stderr: bytes, code: int) -> dict[str, Any]:
    raw = stdout.decode("utf-8", errors="replace").strip()
    if not raw:
        err = stderr.decode("utf-8", errors="replace").strip()
        return {"error": err[:500] or f"Sandbox exit {code}"}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "Réponse sandbox illisible"}
    if isinstance(loaded, dict):
        return loaded
    return {"error": "Réponse sandbox invalide"}


def _env() -> dict[str, str]:
    kept = ("SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP")
    env = {key: os.environ[key] for key in kept if key in os.environ}
    root = Path(__file__).resolve().parents[3]
    env["PYTHONPATH"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env
