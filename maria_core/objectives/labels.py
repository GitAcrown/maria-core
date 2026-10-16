"""Le nom d'un objectif tel qu'on le montre : Rappel, Écoute, Surveillance…"""

from collections.abc import Mapping
from typing import Any

from maria_core.objectives.model import Objective

_LISTEN = frozenset(
    {"on_topic", "on_mention", "on_post", "on_link", "on_attachment", "on_reaction", "on_reply_to"}
)
_RECURRING = frozenset({"daily", "weekly", "interval"})
_OPS = {
    "pause": "en pause",
    "resume": "reprise",
    "cancel": "supprimée",
    "skip": "prochaine occurrence sautée",
    "confirm": "activée",
    "modify": "modifiée",
}


def kind_label(
    trigger: Mapping[str, Any],
    action: Mapping[str, Any] | str | None,
    condition: Mapping[str, Any] | None = None,
) -> str:
    kind = str(trigger.get("type") or "")
    act = str(action.get("type") if isinstance(action, Mapping) else action or "")
    if condition and str(condition.get("type") or "").startswith("price_"):
        return "Veille de prix"
    if act == "fetch_then":
        return "Surveillance"
    if kind in _LISTEN:
        return "Écoute"
    if kind == "on_voice":
        return "Alerte vocale"
    if kind == "on_member_join":
        return "Alerte d'arrivée"
    if kind == "at":
        return "Rappel"
    if kind in _RECURRING:
        return "Rappel récurrent" if act in {"remind", "report", ""} else "Tâche programmée"
    return "Tâche"


def route(objective: Objective) -> str:
    """Où il part : dans le salon (lequel) ou en message privé."""
    if objective.deliver == "dm":
        return "en message privé"
    if objective.channel_ids:
        return f"dans <#{objective.channel_ids[0]}>"
    return "dans le salon"


def op_label(op: str) -> str:
    return _OPS.get(op, "mise à jour")


def status_label(status: str, kind: str) -> str:
    if status == "draft":
        return "brouillon"
    if status == "paused":
        return "en pause"
    if status == "failed":
        return "échec"
    if kind == "Écoute":
        return "à l'écoute"
    if kind in {"Surveillance", "Veille de prix"}:
        return "en veille"
    return "active"


def condition_text(condition: Mapping[str, Any] | None) -> str:
    if not condition:
        return ""
    kind = str(condition.get("type") or "")
    threshold = condition.get("threshold", condition.get("percent"))
    amount = f"{float(threshold):g}" if isinstance(threshold, int | float) else "?"
    return {
        "price_below": f"prix sous {amount} €",
        "price_above": f"prix au-dessus de {amount} €",
        "price_drop": f"baisse de {amount} %",
        "price_lower": "prix plus bas qu'au relevé précédent",
        "price_higher": "prix plus haut qu'au relevé précédent",
        "page_changed": f"dès que ça change ({condition.get('text') or 'contenu principal'})",
    }.get(kind, str(condition.get("text") or ""))
