"""Une tâche MARIA_R devient un objectif, ou une ligne du rapport."""

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta

from maria_core.legacy.model import ObjectiveDraft, Skip
from maria_core.legacy.read import as_dict, cell, moment, positive
from maria_core.legacy.triggers import count, skip_task, trigger_of
from maria_core.objectives.schedule import EVENT_TRIGGERS, first_due

_SOURCE = "tâche"
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_PRICE = {
    "lt": "price_below",
    "lte": "price_below",
    "gt": "price_above",
    "lt_prev": "price_lower",
    "gt_prev": "price_higher",
}
_DRAFT_TTL = timedelta(minutes=10)


def convert_tasks(
    rows: list[sqlite3.Row] | None,
    variables: list[sqlite3.Row] | None,
    *,
    now: datetime,
) -> tuple[tuple[ObjectiveDraft, ...], tuple[Skip, ...]]:
    drafts: list[ObjectiveDraft] = []
    skips: list[Skip] = []
    for row in rows or []:
        built = convert_task(row, now=now)
        if isinstance(built, Skip):
            skips.append(built)
        else:
            drafts.append(built)
    priced, extra = attach_prices(tuple(drafts), variables or [], now)
    return priced, tuple([*skips, *extra])


def convert_task(row: sqlite3.Row, *, now: datetime) -> ObjectiveDraft | Skip:
    status = _status(row, now)
    if isinstance(status, Skip):
        return status
    name, notice = status
    kind = _kind(row)
    trigger = trigger_of(row, kind)
    if isinstance(trigger, Skip):
        return trigger
    built, trigger_notice = trigger
    action = _action(row, kind)
    if isinstance(action, Skip):
        return action
    payload, condition = action
    due = _due(row, built, now)
    if isinstance(due, Skip):
        return due
    expires = _expires(row)
    if isinstance(expires, Skip):
        return expires
    owner = positive(cell(row, "user_id", 0))
    if owner is None:
        return skip_task(row, "auteur absent")
    notes = " ; ".join(part for part in (notice, trigger_notice) if part)
    return _draft(row, owner, name, built, payload, condition, due, expires, notes, now)


def attach_prices(
    drafts: tuple[ObjectiveDraft, ...],
    variables: list[sqlite3.Row],
    now: datetime,
) -> tuple[tuple[ObjectiveDraft, ...], tuple[Skip, ...]]:
    grouped = _by_var(drafts)
    prices: dict[str, float] = {}
    skips: list[Skip] = []
    for row in variables:
        placed = _place_var(row, grouped, now)
        if isinstance(placed, Skip):
            skips.append(placed)
        elif placed is not None:
            prices[placed[0]] = placed[1]
    updated = tuple(
        replace(item, state={"price": prices[item.legacy_id]}) if item.legacy_id in prices else item
        for item in drafts
    )
    return updated, tuple(skips)


def _by_var(drafts: tuple[ObjectiveDraft, ...]) -> dict[tuple[int, int, str], list[str]]:
    grouped: dict[tuple[int, int, str], list[str]] = {}
    for item in drafts:
        if not item.var_key:
            continue
        key = (item.guild_id or 0, item.owner_id, item.var_key)
        grouped.setdefault(key, []).append(item.legacy_id)
    return grouped


def _place_var(
    row: sqlite3.Row,
    grouped: dict[tuple[int, int, str], list[str]],
    now: datetime,
) -> tuple[str, float] | Skip | None:
    if _expired_var(row, now):
        return _var_skip(row, "variable expirée", loud=False)
    key = (
        positive(cell(row, "guild_id", 0)) or 0,
        positive(cell(row, "user_id", 0)) or 0,
        _var_name(row),
    )
    owners = grouped.get(key, [])
    if len(owners) != 1:
        reason = (
            "variable sans objectif" if not owners else "variable partagée par plusieurs objectifs"
        )
        return _var_skip(row, reason)
    try:
        return owners[0], float(str(cell(row, "value_json", "")))
    except ValueError:
        return _var_skip(row, "valeur non numérique")


def _status(row: sqlite3.Row, now: datetime) -> tuple[str, str] | Skip:
    status = str(cell(row, "status", "pending") or "pending").strip()
    if status in _TERMINAL:
        return skip_task(row, "statut terminal", loud=False)
    if status == "draft":
        return _draft_status(row, now)
    if status == "paused":
        return "paused", ""
    if status == "running":
        return "active", "reprise d'une exécution interrompue"
    if status in {"pending", "armed"}:
        return "active", ""
    return skip_task(row, f"statut inconnu ({status})")


def _draft_status(row: sqlite3.Row, now: datetime) -> tuple[str, str] | Skip:
    created = moment(cell(row, "created_at", ""))
    if created is None or now - created > _DRAFT_TTL:
        return skip_task(row, "brouillon expiré", loud=False)
    return "draft", ""


def _kind(row: sqlite3.Row) -> str:
    kind = str(cell(row, "kind", "") or "").strip()
    schedule = str(cell(row, "schedule_kind", "once") or "once").strip()
    if kind in {"", "at"} and schedule in {"daily", "weekly"}:
        return "recurring"
    return kind or "at"


def _action(
    row: sqlite3.Row, kind: str
) -> tuple[dict[str, object], dict[str, object] | None] | Skip:
    planned = _plan(row, kind)
    if isinstance(planned, Skip):
        return planned
    if planned is None:
        return _reminder(row)
    return _from_plan(row, planned)


def _from_plan(
    row: sqlite3.Row, plan: dict[str, object]
) -> tuple[dict[str, object], dict[str, object] | None] | Skip:
    primary = plan.get("primary")
    body = primary if isinstance(primary, dict) else {}
    condition = _condition(row, plan.get("condition"))
    if isinstance(condition, Skip):
        return condition
    kind = str(body.get("type") or "")
    text = _say(plan, row)
    if kind == "read_url":
        return _fetch(row, body, text, condition)
    if kind == "web_search":
        return _search(row, body, text, condition)
    if kind == "prompt":
        return _prompt(row, body, text, condition)
    if condition is not None and condition.get("type") != "judge":
        return skip_task(row, "condition de prix sans lecture de page")
    if condition is not None:
        condition = {**condition, "when": "before"}
    reminder = _reminder(row, text)
    if isinstance(reminder, Skip):
        return reminder
    return reminder[0], condition


def _plan(row: sqlite3.Row, kind: str) -> dict[str, object] | Skip | None:
    recipe = as_dict(cell(row, "recipe_json", ""))
    stored = recipe.get("plan")
    if isinstance(stored, dict) and any(
        stored.get(key) for key in ("primary", "condition", "secondary")
    ):
        return stored
    if kind != "watch":
        return None
    trigger = as_dict(cell(row, "trigger_json", ""))
    url = str(trigger.get("url") or "").strip()
    if not url:
        return skip_task(row, "veille sans page")
    try:
        threshold = float(str(trigger["threshold"]))
    except (KeyError, ValueError):
        return skip_task(row, "veille sans seuil")
    return {
        "primary": {"type": "read_url", "url": url},
        "condition": {
            "type": "price",
            "op": str(trigger.get("op") or "lt"),
            "threshold": threshold,
        },
        "secondary": {"type": "post", "say": _text(row)},
    }


def _fetch(
    row: sqlite3.Row,
    primary: dict[str, object],
    text: str,
    condition: dict[str, object] | None,
) -> tuple[dict[str, object], dict[str, object] | None] | Skip:
    url = str(primary.get("url") or "").strip()
    if not url:
        return skip_task(row, "lecture sans URL")
    return {"type": "fetch_then", "url": url, "text": text or "Lecture de la page."}, condition


def _search(
    row: sqlite3.Row,
    primary: dict[str, object],
    text: str,
    condition: dict[str, object] | None,
) -> tuple[dict[str, object], dict[str, object] | None] | Skip:
    query = str(primary.get("query") or "").strip()
    if not query:
        return skip_task(row, "recherche sans requête")
    action = {"type": "fetch_then", "url": "", "query": query, "text": text, "write": True}
    return action, condition


def _prompt(
    row: sqlite3.Row,
    primary: dict[str, object],
    text: str,
    condition: dict[str, object] | None,
) -> tuple[dict[str, object], dict[str, object] | None] | Skip:
    say = str(primary.get("say") or text).strip()
    if not say:
        return skip_task(row, "prompt sans texte")
    if condition is None:
        return {"type": "report", "text": say}, None
    if condition.get("type") != "judge":
        return skip_task(row, "condition de prix sur un texte rédigé")
    rule = str(condition.get("text") or "")
    instruction = f"{say}\nN'envoie rien (réponds [[SILENCE]]) sauf si : {rule}."
    return {"type": "report", "text": instruction}, None


def _reminder(
    row: sqlite3.Row, text: str | None = None
) -> tuple[dict[str, object], dict[str, object] | None] | Skip:
    """MARIA_R faisait toujours exécuter la consigne par le modèle : c'est un « report »."""
    body = _text(row) if text is None else text.strip()
    if not body:
        return skip_task(row, "rappel sans texte")
    return {"type": "report", "text": body}, None


def _condition(row: sqlite3.Row, raw: object) -> dict[str, object] | Skip | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("type") or "")
    if kind == "judge":
        text = str(raw.get("text") or "").strip()
        return {"type": "judge", "text": text} if text else skip_task(row, "jugement sans texte")
    if kind != "price":
        return skip_task(row, "condition inconnue")
    mapped = _PRICE.get(str(raw.get("op") or "lt"))
    if mapped is None:
        return skip_task(row, f"comparaison de prix non portée ({raw.get('op')})")
    try:
        return {"type": mapped, "threshold": float(str(raw["threshold"]))}
    except (KeyError, ValueError):
        return skip_task(row, "seuil de prix illisible")


def _due(row: sqlite3.Row, trigger: dict[str, object], now: datetime) -> str | Skip | None:
    if trigger.get("type") in EVENT_TRIGGERS:
        return None
    try:
        due = first_due(trigger, now)
    except ValueError:
        return skip_task(row, "échéance illisible")
    if due is None:
        return skip_task(row, "échéance illisible")
    return due.isoformat()


def _draft(
    row: sqlite3.Row,
    owner: int,
    status: str,
    trigger: dict[str, object],
    action: dict[str, object],
    condition: dict[str, object] | None,
    due: str | None,
    expires: str | None,
    notice: str,
    now: datetime,
) -> ObjectiveDraft:
    title = str(cell(row, "title", "") or "").strip() or _text(row) or "Objectif"
    created = moment(cell(row, "created_at", ""))
    return ObjectiveDraft(
        legacy_id=str(cell(row, "id", "?")),
        owner_id=owner,
        guild_id=positive(cell(row, "guild_id", 0)),
        channel_ids=_channels(row),
        deliver="dm" if int(str(cell(row, "deliver_dm", 0) or 0)) else "channel",
        title=title[:200],
        trigger=trigger,
        condition=condition,
        action=action,
        status=status,
        next_run_at=due,
        fires=count(row, "fires_count"),
        max_fires=_limit(row),
        cooldown_s=count(row, "cooldown_seconds"),
        expires_at=expires,
        state={},
        created_at=created.isoformat() if created else now.isoformat(),
        notice=notice,
        var_key=str(as_dict(cell(row, "trigger_json", "")).get("var_key") or "").strip()[:80],
    )


def _channels(row: sqlite3.Row) -> tuple[int, ...]:
    raw = cell(row, "channel_ids", "[]")
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        data = []
    found: list[int] = []
    if isinstance(data, list):
        for item in data:
            number = positive(item)
            if number is not None and number not in found:
                found.append(number)
    if not found:
        channel = positive(cell(row, "channel_id", 0))
        if channel is not None:
            found.append(channel)
    return tuple(found)


def _expires(row: sqlite3.Row) -> str | Skip | None:
    raw = (
        str(cell(row, "expires_at", "") or "").strip()
        or str(cell(row, "until_at", "") or "").strip()
    )
    if not raw:
        return None
    when = moment(raw)
    return when.isoformat() if when else skip_task(row, "expiration illisible")


def _say(plan: dict[str, object], row: sqlite3.Row) -> str:
    secondary = plan.get("secondary")
    if isinstance(secondary, dict) and str(secondary.get("say") or "").strip():
        return str(secondary.get("say") or "").strip()
    return _text(row)


def _text(row: sqlite3.Row) -> str:
    recipe = as_dict(cell(row, "recipe_json", ""))
    return str(recipe.get("say") or cell(row, "instruction", "") or cell(row, "title", "")).strip()


def _limit(row: sqlite3.Row) -> int | None:
    number = count(row, "max_fires")
    return number or None


def _expired_var(row: sqlite3.Row, now: datetime) -> bool:
    when = moment(cell(row, "ttl_expires_at", ""))
    return when is not None and when <= now


def _var_name(row: sqlite3.Row) -> str:
    return str(cell(row, "key", "")).strip()


def _var_skip(row: sqlite3.Row, reason: str, *, loud: bool = True) -> Skip:
    identity = f"{cell(row, 'guild_id', 0)}:{cell(row, 'user_id', 0)}:{_var_name(row)}"
    return Skip("variable", identity, reason, loud)
