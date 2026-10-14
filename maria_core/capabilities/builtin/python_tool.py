"""run_python : ouvert à tous, dans un sous-processus isolé. Un serveur peut le couper."""

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
            blocked = await asyncio.to_thread(_blocked, database, context.guild_id)
            if blocked:
                return Result(ok=False, data={}, error="Python est désactivé sur ce serveur.")
        payload = await asyncio.to_thread(_isolated, str(args.get("code") or ""))
        if "error" in payload:
            return Result(ok=False, data=payload, error=str(payload["error"]))
        return Result(ok=True, data=payload)

    return Capability(
        name="run_python",
        description=(
            "Exécute un court programme Python. math, statistics, datetime, decimal, json et re "
            "sont déjà disponibles (import inutile, les autres modules n'existent pas). "
            "print() et la dernière expression sont renvoyés. "
            "Pas de fichiers ni de réseau, 4 secondes. "
            "Seulement du Python valide, jamais du langage naturel."
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Expression ou petit script Python"},
            },
            "required": ["code"],
        },
        risk=Risk.EXTERNAL,
        run=run,
        timeout_s=8,
    )


def _blocked(database: Database, guild_id: int) -> bool:
    row = database.fetchone(
        "SELECT python_blocked FROM guild_settings WHERE guild_id = ?",
        (guild_id,),
    )
    return row is not None and int(row["python_blocked"]) == 1


def set_python(database: Database, guild_id: int, enabled: bool, now: str) -> None:
    database.execute(
        """
        INSERT INTO guild_settings (guild_id, python_blocked, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            python_blocked = excluded.python_blocked,
            updated_at = excluded.updated_at
        """,
        (guild_id, 0 if enabled else 1, now),
    )


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
