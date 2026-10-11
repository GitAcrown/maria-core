"""Le modèle décrit un objectif à plat. Le noyau en fait le déclencheur, la condition, l'action."""

from collections.abc import Mapping
from typing import Any

from maria_core.objectives.schedule import clock_text, weekdays
from maria_core.objectives.types import ObjectiveTypes


def compile_trigger(args: Mapping[str, Any], types: ObjectiveTypes) -> dict[str, Any]:
    kind = str(args.get("trigger_type") or "")
    _known(kind, types, "trigger")
    if kind == "at":
        return {"type": "at", "at": str(args.get("at") or "")}
    if kind == "daily":
        return {"type": "daily", "time": clock_text(args.get("time") or "09:00")}
    if kind == "weekly":
        days = weekdays(args.get("weekdays"))
        if not days:
            raise ValueError("Indique au moins un jour.")
        return {
            "type": "weekly",
            "time": clock_text(args.get("time") or "09:00"),
            "weekdays": list(days),
        }
    if kind == "interval":
        minutes = _minutes(args.get("every_minutes"))
        return {"type": "interval", "every_s": minutes * 60}
    if kind == "on_topic":
        pattern = str(args.get("pattern") or "").strip()
        if not pattern:
            raise ValueError("Il manque le motif à écouter.")
        return {"type": "on_topic", "pattern": pattern}
    return {"type": kind}


def compile_action(args: Mapping[str, Any], types: ObjectiveTypes) -> dict[str, Any]:
    kind = str(args.get("action_type") or "remind")
    _known(kind, types, "action")
    text = str(args.get("text") or "").strip()
    if kind == "fetch_then":
        url = str(args.get("url") or "").strip()
        if not url:
            raise ValueError("Il manque l'URL à lire.")
        return {"type": "fetch_then", "url": url, "text": text}
    if not text and kind != "alert":
        raise ValueError("Il manque le texte du message.")
    return {"type": kind, "text": text or str(args.get("title") or "")}


def compile_condition(args: Mapping[str, Any], types: ObjectiveTypes) -> dict[str, Any] | None:
    kind = str(args.get("condition_type") or "").strip()
    if not kind:
        return None
    _known(kind, types, "condition")
    if kind == "judge":
        text = str(args.get("condition_text") or args.get("text") or "").strip()
        if not text:
            raise ValueError("Il manque le texte à juger.")
        return {"type": "judge", "text": text}
    if kind == "price_drop":
        return {"type": kind, "percent": _amount(args.get("threshold"))}
    return {"type": kind, "threshold": _amount(args.get("threshold"))}


def _known(kind: str, types: ObjectiveTypes, family: str) -> None:
    if kind not in types.names(family):
        raise ValueError(f"Type inconnu : {kind}.")


def _minutes(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        raise ValueError("Intervalle en minutes manquant.")
    try:
        minutes = int(raw)
    except ValueError as exc:
        raise ValueError("Intervalle illisible.") from exc
    if minutes < 1:
        raise ValueError("L'intervalle minimum est une minute.")
    return minutes


def _amount(raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        raise ValueError("Seuil manquant.")
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError("Seuil illisible.") from exc
