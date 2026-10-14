"""Le modèle décrit un objectif à plat. Le noyau en fait le déclencheur, la condition, l'action."""

import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from maria_core.objectives.quota import MIN_FETCH_INTERVAL_S
from maria_core.objectives.schedule import EVENT_TRIGGERS, clock_text, moment_of, weekdays
from maria_core.objectives.types import ObjectiveTypes

PRICE_CONDITIONS = frozenset(
    {"price_below", "price_above", "price_drop", "price_lower", "price_higher"}
)
_VOICE_EVENTS = frozenset({"join", "leave", "stream"})
_AUTHORS = frozenset({"any", "self", "others"})


def compile_trigger(
    args: Mapping[str, Any], types: ObjectiveTypes, *, now: datetime | None = None
) -> dict[str, Any]:
    kind = str(args.get("trigger_type") or "")
    _known(kind, types, "trigger")
    builder = _TRIGGERS.get(kind)
    trigger = builder(args, now) if builder is not None else {"type": kind}
    if kind in EVENT_TRIGGERS:
        trigger["repeat"] = bool(args.get("repeat"))
    return trigger


def compile_action(args: Mapping[str, Any], types: ObjectiveTypes) -> dict[str, Any]:
    kind = str(args.get("action_type") or "remind")
    _known(kind, types, "action")
    text = str(args.get("text") or "").strip()
    if kind == "fetch_then":
        url = str(args.get("url") or "").strip()
        query = str(args.get("query") or "").strip()
        if not url and not query:
            raise ValueError("fetch_then : donne une url à lire, ou une query à chercher.")
        return {"type": kind, "url": url, "query": query, "text": text, "write": _write(args)}
    if not text and kind != "alert":
        raise ValueError("Il manque le texte du message.")
    return {"type": kind, "text": text or str(args.get("title") or "")}


def compile_condition(args: Mapping[str, Any], types: ObjectiveTypes) -> dict[str, Any] | None:
    kind = str(args.get("condition_type") or "").strip()
    if not kind:
        return None
    _known(kind, types, "condition")
    if kind == "judge":
        text = str(args.get("condition_text") or "").strip()
        if not text:
            raise ValueError("Il manque la condition à juger (condition_text).")
        when = "before" if str(args.get("condition_when") or "") == "before" else "after"
        return {"type": "judge", "text": text, "when": when}
    if kind == "page_changed":
        return {"type": kind, "text": str(args.get("condition_text") or "").strip()}
    if kind == "price_drop":
        return {"type": kind, "percent": _amount(args.get("threshold"))}
    if kind in {"price_lower", "price_higher"}:
        return {"type": kind, "threshold": _optional_amount(args.get("threshold"))}
    return {"type": kind, "threshold": _amount(args.get("threshold"))}


def check_plan(
    trigger: Mapping[str, Any], condition: Mapping[str, Any] | None, action: Mapping[str, Any]
) -> None:
    """Refuse les combinaisons qui spammeraient ou ne peuvent rien vérifier."""
    kind = str(trigger.get("type") or "")
    fetching = action.get("type") == "fetch_then"
    if condition is not None and condition.get("type") in PRICE_CONDITIONS and not fetching:
        raise ValueError("Une condition de prix demande action_type=fetch_then avec une url.")
    if condition is not None and condition.get("type") == "page_changed" and not fetching:
        raise ValueError("page_changed demande action_type=fetch_then avec une url ou une query.")
    if kind == "on_message" and (condition is None or condition.get("type") != "judge"):
        raise ValueError("on_message demande une condition judge, sinon chaque message alerte.")
    if fetching and kind == "interval" and int(trigger.get("every_s") or 0) < MIN_FETCH_INTERVAL_S:
        raise ValueError("Une veille web se vérifie au plus toutes les 6 h.")


_RECURRING = frozenset({"daily", "weekly", "interval"})


def needs_confirmation(
    trigger: Mapping[str, Any], action: Mapping[str, Any], max_fires: int | None
) -> bool:
    """Seuls les suivis qui peuvent devenir pénibles demandent un oui : ce qui se répète
    (rappel récurrent, écoute répétée) et les veilles de page ou de prix.

    Un rappel isolé, ou « préviens-moi une fois si on parle de ça », part tout de suite.
    """
    kind = str(trigger.get("type") or "")
    if kind in _RECURRING or action.get("type") == "fetch_then":
        return True
    return kind in EVENT_TRIGGERS and max_fires != 1


def _at(args: Mapping[str, Any], now: datetime | None) -> dict[str, Any]:
    minutes = args.get("in_minutes")
    if isinstance(minutes, int | float) and not isinstance(minutes, bool) and minutes > 0:
        if now is None:
            raise ValueError("Heure de référence manquante.")
        return {"type": "at", "at": (now + timedelta(minutes=float(minutes))).isoformat()}
    raw = str(args.get("at") or "").strip()
    if not raw:
        raise ValueError("Indique `at` (2026-10-12T20:00, heure de Paris) ou `in_minutes`.")
    moment = moment_of(raw)
    if now is not None and moment < now - timedelta(minutes=5):
        raise ValueError("Cette date est déjà passée.")
    return {"type": "at", "at": moment.isoformat()}


def _daily(args: Mapping[str, Any], _now: datetime | None) -> dict[str, Any]:
    return {"type": "daily", "time": clock_text(args.get("time") or "09:00")}


def _weekly(args: Mapping[str, Any], _now: datetime | None) -> dict[str, Any]:
    days = weekdays(args.get("weekdays"))
    if not days:
        raise ValueError("Indique au moins un jour (weekdays).")
    return {
        "type": "weekly",
        "time": clock_text(args.get("time") or "09:00"),
        "weekdays": list(days),
    }


def _interval(args: Mapping[str, Any], _now: datetime | None) -> dict[str, Any]:
    return {"type": "interval", "every_s": _minutes(args.get("every_minutes")) * 60}


_QUOTES = {ord(char): " " for char in '«»"' + chr(0x201C) + chr(0x201D) + chr(0x201E)}
_KIND = re.compile(
    r"^(?:(?:le|la|les|un|une|des)\s+|l')?"
    r"(?:film|s[eé]rie|jeu(?: vid[eé]o)?|livre|album|chanson|morceau|groupe|artiste|anime|manga|"
    r"dessin anim[eé]|[eé]mission|youtubeur|streamer|marque|application)"
    r"\s+(?:(?:de|du|des|d')\s*)?",
    re.IGNORECASE,
)


def clean_pattern(raw: str) -> str:
    """« le film « Le Corset » » devient « Le Corset » : le nom comme on le dit, article compris.

    « corset » seul ne doit pas suffire : « le corset » est un film, « un corset » n'en est pas un.
    """
    text = " ".join(str(raw).translate(_QUOTES).split())
    stripped = _KIND.sub("", text, count=1).strip()
    return stripped if len(stripped) >= 3 else text


def _topic(args: Mapping[str, Any], _now: datetime | None) -> dict[str, Any]:
    raw = str(args.get("pattern") or "").strip()
    topic = " ".join(str(args.get("topic") or "").translate(_QUOTES).split())
    if not raw and not topic:
        raise ValueError("on_topic : un mot à guetter (pattern) ou un sujet (topic).")
    words = list(dict.fromkeys(w for w in map(clean_pattern, raw.split(",")) if w))
    trigger: dict[str, Any] = {"type": "on_topic", "author": _author(args)}
    if words:
        trigger["pattern"] = words[0]
        trigger["aliases"] = words[1:8]
    if topic:
        trigger["topic"] = topic[:200]
    return trigger


def _message(args: Mapping[str, Any], _now: datetime | None) -> dict[str, Any]:
    return {"type": "on_message", "author": _author(args)}


def _voice(args: Mapping[str, Any], _now: datetime | None) -> dict[str, Any]:
    event = str(args.get("voice_event") or "join")
    if event not in _VOICE_EVENTS:
        raise ValueError("voice_event : join, leave ou stream.")
    trigger: dict[str, Any] = {"type": "on_voice", "signal": event}
    target = _identifier(args.get("target_user_id"))
    if target is not None:
        trigger["user_id"] = target
    place = _identifier(args.get("voice_channel_id"))
    if place is not None:
        trigger["voice_channel_id"] = place
    return trigger


_TRIGGERS: dict[str, Callable[[Mapping[str, Any], datetime | None], dict[str, Any]]] = {
    "at": _at,
    "daily": _daily,
    "weekly": _weekly,
    "interval": _interval,
    "on_topic": _topic,
    "on_message": _message,
    "on_voice": _voice,
}


def _author(args: Mapping[str, Any]) -> str:
    raw = str(args.get("author") or "others").strip()
    if raw in _AUTHORS or raw.isdigit():
        return raw
    return "others"


def _write(args: Mapping[str, Any]) -> bool:
    raw = args.get("write")
    return raw is True


def _identifier(raw: object) -> int | None:
    text = str(raw or "").strip()
    return int(text) if text.isdigit() else None


def _known(kind: str, types: ObjectiveTypes, family: str) -> None:
    if kind not in types.names(family):
        allowed = ", ".join(types.names(family))
        raise ValueError(f"Type inconnu : {kind or '(vide)'}. Possibles : {allowed}.")


def _minutes(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        raise ValueError("Intervalle en minutes manquant (every_minutes).")
    try:
        minutes = int(raw)
    except ValueError as exc:
        raise ValueError("Intervalle illisible.") from exc
    if minutes < 1:
        raise ValueError("L'intervalle minimum est une minute.")
    return minutes


def _amount(raw: object) -> float:
    value = _optional_amount(raw)
    if value is None:
        raise ValueError("Seuil manquant (threshold).")
    return value


def _optional_amount(raw: object) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        raise ValueError("Seuil illisible.")
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError("Seuil illisible.") from exc
