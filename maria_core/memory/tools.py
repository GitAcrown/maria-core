"""remember_fact, search_memory, forget_fact."""

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.memory.policy import Actor, denial
from maria_core.memory.service import Memories
from maria_core.memory.store import MemoryDenied

_REMEMBER = (
    "Retient un fait précis et confirmé. scope=user : la personne qui parle, ou subject_user_id "
    "pour quelqu'un d'autre (ça devient une proposition qu'iel validera). scope=guild : le "
    "serveur (modérateur, sinon proposition). scope=self : tes propres goûts ; origin=own si "
    "c'est ton avis à toi, owner si ton créateur te l'impose. memory_id : corrige un souvenir "
    "faux au lieu d'en créer un nouveau. Écris le fait à la 3e personne, court."
)


def memory_capabilities(memories: Memories) -> tuple[Capability, ...]:
    return (
        Capability(
            name="remember_fact",
            description=_REMEMBER,
            parameters=_remember_schema(),
            risk=Risk.WRITE,
            run=_remember(memories),
        ),
        Capability(
            name="search_memory",
            description=(
                "Cherche dans les souvenirs acceptés (personne, goût, surnom, projet, chose déjà "
                "dite) quand ce n'est pas déjà dans le prompt. Les propositions n'y sont pas."
            ),
            parameters=_query_schema(),
            risk=Risk.READ,
            run=_search(memories),
        ),
        Capability(
            name="forget_fact",
            description="Oublie un souvenir par id. Il disparaît tout de suite.",
            parameters={
                "type": "object",
                "properties": {"id": {"type": "integer"}},
                "required": ["id"],
            },
            risk=Risk.WRITE,
            run=_forget(memories),
        ),
    )


def _remember(memories: Memories) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        content = str(args.get("content") or "").strip()
        if not content:
            return Result(ok=False, data={}, error="Souvenir vide.")
        actor = _actor(context)
        try:
            if args.get("memory_id"):
                memory = await asyncio.to_thread(
                    memories.store.correct, actor, int(args["memory_id"]), content, memories.now()
                )
                return Result(ok=True, data={"id": memory.id, "content": memory.content})
            return await _write(memories, context, actor, args, content)
        except (MemoryDenied, ValueError) as exc:
            return Result(ok=False, data={}, error=str(exc))

    return run


async def _write(
    memories: Memories, context: Context, actor: Actor, args: Mapping[str, Any], content: str
) -> Result:
    scope = str(args.get("scope") or "user")
    subject = _subject(scope, context, args)
    own = scope == "self" and str(args.get("origin") or "own") == "own"
    if not own and denial(actor, scope, subject):
        return await _propose(memories, context, scope, subject, content)
    memory = await asyncio.to_thread(
        memories.store.remember,
        actor,
        scope=scope,
        subject_id=subject,
        guild_id=context.guild_id,
        content=content,
        source="explicit",
        now=memories.now(),
        own=own,
    )
    return Result(ok=True, data={"id": memory.id, "content": memory.content})


async def _propose(
    memories: Memories, context: Context, scope: str, subject: int, content: str
) -> Result:
    if scope == "self":
        return Result(ok=False, data={}, error="Tes goûts viennent de toi ou de ton créateur.")
    proposal = await asyncio.to_thread(
        memories.store.propose,
        scope=scope,
        content=content,
        subject_user_id=subject if scope == "user" else None,
        guild_id=context.guild_id,
        channel_id=context.channel_id,
        source_message_id=context.message_id,
        now=memories.now(),
    )
    who = "la personne concernée" if scope == "user" else "un modérateur"
    return Result(
        ok=True,
        data={
            "proposed": proposal.id,
            "content": proposal.content,
            "note": f"Pas encore retenu : {who} doit valider (/moi ou /global).",
        },
    )


def _search(memories: Memories) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        hits = await asyncio.to_thread(
            memories.store.search,
            str(args.get("query") or ""),
            user_id=context.user_id,
            guild_id=context.guild_id,
            limit=8,
        )
        await asyncio.to_thread(
            memories.store.mark_used, tuple(item.id for item in hits), memories.now()
        )
        found = [
            {"id": item.id, "about": _about(item.scope, item.subject_id), "content": item.content}
            for item in hits
        ]
        return Result(ok=True, data={"memories": found})

    return run


def _forget(memories: Memories) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        try:
            removed = await asyncio.to_thread(
                memories.store.forget, _actor(context), int(args["id"]), memories.now()
            )
        except MemoryDenied as exc:
            return Result(ok=False, data={}, error=str(exc))
        if not removed:
            return Result(ok=False, data={}, error="Souvenir introuvable.")
        return Result(ok=True, data={"id": int(args["id"])})

    return run


def _about(scope: str, subject_id: int) -> str:
    if scope == "self":
        return "toi"
    if scope == "guild":
        return "serveur"
    return f"membre {subject_id}"


def _actor(context: Context) -> Actor:
    return Actor(context.user_id, context.is_owner, context.is_moderator)


def _subject(scope: str, context: Context, args: Mapping[str, Any]) -> int:
    if scope == "self":
        return 0
    if scope == "guild":
        return context.guild_id or 0
    raw = str(args.get("subject_user_id") or "").strip()
    return int(raw) if raw.isdigit() else context.user_id


def _remember_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "scope": {"type": "string", "enum": ["user", "guild", "self"]},
            "subject_user_id": {"type": "string", "description": "Id Discord de la personne"},
            "memory_id": {"type": "integer", "description": "Souvenir à corriger"},
            "origin": {"type": "string", "enum": ["own", "owner"]},
        },
        "required": ["content"],
    }


def _query_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
