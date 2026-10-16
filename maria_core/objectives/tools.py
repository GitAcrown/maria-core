"""Outils du modèle : créer, modifier, lister, montrer. Le noyau compile, le modèle décrit."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.objectives.compile import (
    check_plan,
    compile_action,
    compile_condition,
    compile_trigger,
    needs_confirmation,
)
from maria_core.objectives.labels import condition_text, kind_label, op_label, recipient, route
from maria_core.objectives.model import Objective, ObjectiveQuota, StaleObjective
from maria_core.objectives.schedule import EVENT_TRIGGERS, describe, first_due, next_due
from maria_core.objectives.schemas import create_schema, update_schema

_OPS = ("pause", "resume", "cancel", "skip", "confirm", "modify")
_REPEAT_COOLDOWN = 3 * 3600
_CREATE = (
    "Crée un objectif : rappel, récap programmé, veille de page ou de prix, écoute d'un mot, "
    "d'un sujet ou d'un vocal. Une heure dite = at (date de Paris) ou in_minutes ; une "
    "récurrence = daily/weekly. Un objectif conditionnel ou une écoute devient un brouillon : "
    "dis en une phrase quand tu vérifies et que tu te tais si c'est faux, puis attends le oui. "
    "Doublon : l'id existant est renvoyé, propose de le modifier."
)
_UPDATE = (
    "pause, resume, cancel, skip (passe la prochaine occurrence), confirm (valide un brouillon "
    "après un oui) ou modify (change seulement les champs donnés)."
)


def objective_capabilities(service: Any) -> tuple[Capability, ...]:
    return (
        _tool("objective_create", _CREATE, create_schema(), Risk.WRITE, _create(service)),
        _tool("objective_update", _UPDATE, update_schema(), Risk.WRITE, _update(service)),
        _tool(
            "objective_list",
            "Liste les objectifs ouverts de la personne (brouillons, actifs, en pause).",
            {"type": "object", "properties": {}, "required": []},
            Risk.READ,
            _list(service),
        ),
        _tool(
            "objective_show",
            "Détail d'un objectif, par id.",
            {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
            Risk.READ,
            _show(service),
        ),
    )


def _create(service: Any) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        if not await _asked_for(service, context, args):
            return Result(
                ok=False,
                data={},
                error=(
                    "La personne n'a pas demandé à être prévenue : ne crée rien. Si tu veux, "
                    "propose-le-lui en une phrase."
                ),
            )
        try:
            target = await _target(service, context, args)
            objective, created = _build(service, context, args, target)
        except (ObjectiveQuota, ValueError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        data = public(objective)
        if not created:
            data["duplicate"] = True
            data["hint"] = "Cet objectif existe déjà. Propose de le modifier."
        elif objective.status == "draft":
            data["hint"] = "Brouillon : explique en une phrase, il part après un oui."
        draft = created and objective.status == "draft"
        widget = None if not created else "objective_draft" if draft else "objective_created"
        return Result(ok=True, data=data, widget=widget)

    return run


async def _target(
    service: Any, context: Context, args: Mapping[str, Any]
) -> tuple[int, str] | None:
    """Quelqu'un d'autre que l'auteur : son id et son nom, vérifiés sur le serveur."""
    raw = str(args.get("for_user_id") or "").strip()
    if not raw.isdigit() or int(raw) == context.user_id:
        return None
    if context.guild_id is None:
        raise ValueError("Un rappel pour quelqu'un d'autre se crée sur un serveur.")
    find = getattr(service, "member_name", None)
    name = await find(context.guild_id, int(raw)) if find is not None else ""
    if name is None:
        raise ValueError("Je ne trouve pas ce membre sur ce serveur.")
    return int(raw), name


def _build(
    service: Any, context: Context, args: Mapping[str, Any], target: tuple[int, str] | None = None
) -> tuple[Objective, bool]:
    now = service.now()
    trigger = compile_trigger(args, service.types, now=now)
    action = compile_action(args, service.types)
    condition = compile_condition(args, service.types)
    check_plan(trigger, condition, action)
    if target is not None and (
        trigger["type"] != "at" or action["type"] != "remind" or condition is not None
    ):
        raise ValueError(
            "Un rappel pour quelqu'un d'autre est un rappel à date ou à heure, au texte fixe : "
            "ni écoute, ni récurrence, ni condition."
        )
    deliver = "dm" if context.guild_id is None else str(args.get("deliver") or "channel")
    repeat = bool(trigger.get("repeat"))
    limit = _max_fires(trigger, args, repeat)
    return service.store.create(
        owner_id=context.user_id,
        guild_id=context.guild_id,
        channel_ids=()
        if deliver == "dm" and trigger["type"] not in EVENT_TRIGGERS
        else (context.channel_id,),
        deliver=deliver,
        title=str(args.get("title") or action.get("text") or "Rappel")[:120],
        trigger=trigger,
        condition=condition,
        action=action,
        now=now,
        max_fires=limit,
        cooldown_s=_REPEAT_COOLDOWN if repeat and trigger["type"] in EVENT_TRIGGERS else 0,
        status="draft"
        if needs_confirmation(trigger, action, limit, other=bool(target))
        else "active",
        origin_message_id=context.message_id,
        state={"spec": _spec(args), **({"target_name": target[1]} if target else {})},
        target_id=target[0] if target else None,
    )


async def _asked_for(service: Any, context: Context, args: Mapping[str, Any]) -> bool:
    """Une écoute ne naît que d'une demande claire, jamais d'une simple remarque."""
    check = getattr(service, "is_request", None)
    if check is None or str(args.get("trigger_type") or "") not in EVENT_TRIGGERS:
        return True
    return bool(await check(context.text))


def _max_fires(trigger: Mapping[str, Any], args: Mapping[str, Any], repeat: bool) -> int | None:
    raw = args.get("max_fires")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    if trigger["type"] == "at":
        return 1
    if trigger["type"] in EVENT_TRIGGERS and not repeat:
        return 1
    return None


def _update(service: Any) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        objective = service.store.get(int(args["id"]))
        if objective is None:
            return Result(ok=False, data={}, error="Objectif introuvable.")
        if objective.owner_id != context.user_id and not context.is_owner:
            return Result(ok=False, data={}, error="Ce n'est pas ton objectif.")
        try:
            saved = apply(service, objective, args)
        except (StaleObjective, ValueError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        return Result(ok=True, data={**public(saved), "done": op_label(str(args.get("op") or ""))})

    return run


def _list(service: Any) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(context: Context, _args: Mapping[str, Any]) -> Result:
        items = [public(item) for item in service.store.list_for(context.user_id)]
        return Result(ok=True, data={"objectives": items})

    return run


def _show(service: Any) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        objective = service.store.get(int(args["id"]))
        if objective is None or (objective.owner_id != context.user_id and not context.is_owner):
            return Result(ok=False, data={}, error="Objectif introuvable.")
        return Result(ok=True, data={**public(objective), "spec": objective.state.get("spec")})

    return run


def operate(service: Any, owner_id: int, objective_id: int, op: str) -> Objective:
    """Pause, reprise, saut, annulation ou confirmation, pour les menus."""
    objective = service.store.get(objective_id)
    if objective is None or objective.owner_id != owner_id:
        raise ValueError("Objectif introuvable.")
    if op not in {"pause", "resume", "cancel", "skip", "confirm"}:
        raise ValueError("Opération inconnue.")
    return apply(service, objective, {"op": op})


def apply(service: Any, objective: Objective, args: Mapping[str, Any]) -> Objective:
    now = service.now()
    op = str(args["op"])
    if op == "pause":
        return _status(service, objective, now, "paused", objective.next_run_at)
    if op in {"resume", "confirm"}:
        if op == "confirm" and objective.status != "draft":
            raise ValueError("Rien à confirmer.")
        return _status(service, objective, now, "active", _resume_at(objective, now))
    if op == "cancel":
        return _status(service, objective, now, "cancelled", None)
    if op == "skip":
        return _skip(service, objective, now)
    if op == "modify":
        return _modify(service, objective, args, now)
    raise ValueError(f"Opération inconnue : {op}.")


def _resume_at(objective: Objective, now: datetime) -> datetime | None:
    nxt = objective.next_run_at
    if nxt is None or nxt <= now:
        return first_due(objective.trigger, now)
    return nxt


def _skip(service: Any, objective: Objective, now: datetime) -> Objective:
    if str(objective.trigger.get("type") or "") == "at":
        return _status(service, objective, now, "done", None)
    due = objective.next_run_at
    anchor = due if due is not None and due > now else now
    return _status(service, objective, now, "active", next_due(objective.trigger, after=anchor))


def _modify(
    service: Any, objective: Objective, args: Mapping[str, Any], now: datetime
) -> Objective:
    """Les champs donnés remplacent ceux de la création ; le reste est gardé."""
    changes = {key: value for key, value in args.items() if key not in {"id", "op"}}
    spec = {**dict(objective.state.get("spec") or _guess_spec(objective)), **changes}
    trigger = compile_trigger(spec, service.types, now=now)
    action = compile_action(spec, service.types)
    condition = compile_condition(spec, service.types) if spec.get("condition_type") else None
    check_plan(trigger, condition, action)
    repeat = bool(trigger.get("repeat"))
    return service.store.revise(
        objective,
        now=now,
        title=str(spec.get("title") or objective.title),
        trigger=trigger,
        condition=condition,
        action=action,
        next_run_at=first_due(trigger, now),
        deliver=str(spec.get("deliver") or objective.deliver),
        max_fires=_max_fires(trigger, spec, repeat),
        state={**objective.state, "spec": _spec(spec)},
    )


def _guess_spec(objective: Objective) -> dict[str, Any]:
    """Objectif importé sans description à plat : on la reconstruit."""
    trigger, action = objective.trigger, objective.action
    spec: dict[str, Any] = {
        "title": objective.title,
        "trigger_type": trigger.get("type"),
        "action_type": action.get("type"),
        "text": action.get("text"),
        "url": action.get("url"),
        "time": trigger.get("time"),
        "at": trigger.get("at"),
        "weekdays": ",".join(trigger.get("weekdays") or []),
        "every_minutes": int(trigger.get("every_s") or 0) // 60 or None,
        "pattern": trigger.get("pattern"),
    }
    if objective.condition is not None:
        spec["condition_type"] = objective.condition.get("type")
        spec["condition_text"] = objective.condition.get("text")
        spec["threshold"] = objective.condition.get("threshold", objective.condition.get("percent"))
    return {key: value for key, value in spec.items() if value not in (None, "")}


def _status(
    service: Any, objective: Objective, now: datetime, status: str, nxt: datetime | None
) -> Objective:
    return service.store.settle(
        objective,
        now=now,
        status=status,
        next_run_at=nxt,
        fires=objective.fires,
        state=objective.state,
    )


def public(objective: Objective) -> dict[str, Any]:
    return {
        "id": objective.id,
        "title": objective.title,
        "kind": kind_label(objective.trigger, objective.action, objective.condition),
        "status": objective.status,
        "when": describe(objective.trigger),
        "condition": dict(objective.condition) if objective.condition else None,
        "if": condition_text(objective.condition),
        "say": str(objective.action.get("text") or ""),
        "action": objective.action.get("type"),
        "next_run_at": objective.next_run_at.isoformat() if objective.next_run_at else None,
        "fires": objective.fires,
        "max_fires": objective.max_fires,
        "deliver": objective.deliver,
        "for": recipient(objective),
        "where": route(objective),
    }


def _spec(args: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in args.items() if value is not None and key != "op"}


def _tool(
    name: str, description: str, parameters: dict[str, Any], risk: Risk, run: Any
) -> Capability:
    return Capability(name=name, description=description, parameters=parameters, risk=risk, run=run)


def _now() -> datetime:
    return datetime.now(UTC)
