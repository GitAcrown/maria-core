"""Outils du modèle : créer, modifier, lister, montrer."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.objectives.compile import compile_action, compile_condition, compile_trigger
from maria_core.objectives.model import Objective, ObjectiveQuota, StaleObjective
from maria_core.objectives.schedule import describe, first_due, next_due

_OPS = ("pause", "resume", "cancel", "skip", "confirm", "modify")
_CREATE = (
    "Crée un objectif. S'il en existe déjà un pareil, renvoie son id : "
    "propose alors une modification, pas un doublon."
)
_UPDATE = "pause, resume, cancel, skip, confirm ou modify. modify redéfinit l'échéance."


def objective_capabilities(service: Any) -> tuple[Capability, ...]:
    return (
        _tool("objective_create", _CREATE, _create_schema(), Risk.WRITE, _create(service)),
        _tool("objective_update", _UPDATE, _update_schema(), Risk.WRITE, _update(service)),
        _tool(
            "objective_list",
            "Liste les objectifs ouverts de la personne.",
            _empty(),
            Risk.READ,
            _list(service),
        ),
        _tool(
            "objective_show",
            "Détail d'un objectif, par id.",
            _show_schema(),
            Risk.READ,
            _show(service),
        ),
    )


def _create(service: Any) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        try:
            trigger = compile_trigger(args, service.types)
            action = compile_action(args, service.types)
            condition = compile_condition(args, service.types)
            deliver = "dm" if context.guild_id is None else str(args.get("deliver") or "channel")
            channels = () if deliver == "dm" else (context.channel_id,)
            objective, created = service.store.create(
                owner_id=context.user_id,
                guild_id=context.guild_id,
                channel_ids=channels,
                deliver=deliver,
                title=str(args.get("title") or "Rappel"),
                trigger=trigger,
                condition=condition,
                action=action,
                now=service.now(),
                max_fires=1 if trigger["type"] == "at" else None,
            )
        except (ObjectiveQuota, ValueError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        data = _public(objective)
        if not created:
            data["duplicate"] = True
            data["hint"] = "Cet objectif existe déjà. Propose une modification."
        return Result(ok=True, data=data)

    return run


def _update(service: Any) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        objective = service.store.get(int(args["id"]))
        if objective is None:
            return Result(ok=False, data={}, error="Objectif introuvable.")
        if objective.owner_id != context.user_id and not context.is_owner:
            return Result(ok=False, data={}, error="Ce n'est pas ton objectif.")
        try:
            saved = _apply(service, objective, args)
        except (StaleObjective, ValueError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        return Result(ok=True, data=_public(saved))

    return run


def _list(service: Any) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(context: Context, _args: Mapping[str, Any]) -> Result:
        items = [_public(item) for item in service.store.list_for(context.user_id)]
        return Result(ok=True, data={"objectives": items})

    return run


def _show(service: Any) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        objective = service.store.get(int(args["id"]))
        if objective is None or (objective.owner_id != context.user_id and not context.is_owner):
            return Result(ok=False, data={}, error="Objectif introuvable.")
        return Result(ok=True, data=_public(objective))

    return run


def _apply(service: Any, objective: Objective, args: Mapping[str, Any]) -> Objective:
    now = service.now()
    op = str(args["op"])
    if op == "pause":
        return _status(service, objective, now, "paused", objective.next_run_at)
    if op == "resume":
        nxt = objective.next_run_at
        if nxt is None or nxt <= now:
            nxt = first_due(objective.trigger, now)
        return _status(service, objective, now, "active", nxt)
    if op == "cancel":
        return _status(service, objective, now, "cancelled", None)
    if op == "confirm":
        if objective.status != "draft":
            raise ValueError("Rien à confirmer.")
        return _status(service, objective, now, "active", first_due(objective.trigger, now))
    if op == "skip":
        return _skip(service, objective, now)
    if op == "modify":
        return _modify(service, objective, args, now)
    raise ValueError(f"Opération inconnue : {op}.")


def _skip(service: Any, objective: Objective, now: datetime) -> Objective:
    if str(objective.trigger.get("type") or "") == "at":
        return _status(service, objective, now, "done", None)
    due = objective.next_run_at
    anchor = due if due is not None and due > now else now
    return _status(service, objective, now, "active", next_due(objective.trigger, after=anchor))


def _modify(
    service: Any, objective: Objective, args: Mapping[str, Any], now: datetime
) -> Objective:
    trigger = (
        compile_trigger(args, service.types) if args.get("trigger_type") else objective.trigger
    )
    action = compile_action(args, service.types) if args.get("action_type") else objective.action
    title = str(args.get("title") or objective.title)
    return service.store.revise(
        objective,
        now=now,
        title=title,
        trigger=trigger,
        condition=objective.condition,
        action=action,
        next_run_at=first_due(trigger, now),
    )


def _status(
    service: Any,
    objective: Objective,
    now: datetime,
    status: str,
    nxt: datetime | None,
) -> Objective:
    return service.store.settle(
        objective,
        now=now,
        status=status,
        next_run_at=nxt,
        fires=objective.fires,
        state=objective.state,
    )


def _public(objective: Objective) -> dict[str, Any]:
    return {
        "id": objective.id,
        "title": objective.title,
        "status": objective.status,
        "when": describe(objective.trigger),
        "next_run_at": objective.next_run_at.isoformat() if objective.next_run_at else None,
        "fires": objective.fires,
        "version": objective.version,
    }


def _tool(
    name: str, description: str, parameters: dict[str, Any], risk: Risk, run: Any
) -> Capability:
    return Capability(name=name, description=description, parameters=parameters, risk=risk, run=run)


def _empty() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "required": []}


def _create_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "trigger_type": {"type": "string"},
            "action_type": {"type": "string"},
            "text": {"type": "string"},
            "time": {"type": "string"},
            "at": {"type": "string"},
            "weekdays": {"type": "string"},
            "every_minutes": {"type": "integer", "minimum": 1},
            "pattern": {"type": "string"},
            "url": {"type": "string"},
            "deliver": {"type": "string", "enum": ["channel", "dm"]},
            "condition_type": {"type": "string"},
            "condition_text": {"type": "string"},
            "threshold": {"type": "number"},
        },
        "required": ["title", "trigger_type", "action_type"],
    }


def _update_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "op": {"type": "string", "enum": list(_OPS)},
            "title": {"type": "string"},
            "trigger_type": {"type": "string"},
            "action_type": {"type": "string"},
            "text": {"type": "string"},
            "time": {"type": "string"},
            "at": {"type": "string"},
            "weekdays": {"type": "string"},
            "every_minutes": {"type": "integer"},
            "pattern": {"type": "string"},
            "url": {"type": "string"},
        },
        "required": ["id", "op"],
    }


def _show_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    }


def _now() -> datetime:
    return datetime.now(UTC)
