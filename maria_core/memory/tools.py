"""remember_fact, search_memory, forget_fact."""

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.memory.policy import Actor, denial
from maria_core.memory.service import Memories
from maria_core.memory.store import MemoryDenied


def memory_capabilities(memories: Memories) -> tuple[Capability, ...]:
    return (
        Capability(
            name="remember_fact",
            description=(
                "Retient un fait demandé explicitement. scope=user pour la personne, "
                "guild pour le serveur (modérateur, sinon une proposition), "
                "self pour MARIA (propriétaire)."
            ),
            parameters=_remember_schema(),
            risk=Risk.WRITE,
            run=_remember(memories),
        ),
        Capability(
            name="search_memory",
            description="Cherche un souvenir déjà accepté. Les propositions n'y sont pas.",
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
        scope = str(args.get("scope") or "user")
        actor = _actor(context)
        subject = _subject(scope, context)
        if scope == "guild" and denial(actor, scope, subject):
            proposal = await asyncio.to_thread(
                memories.store.propose,
                scope="guild",
                content=content,
                subject_user_id=None,
                guild_id=context.guild_id,
                channel_id=context.channel_id,
                source_message_id=context.message_id,
                now=memories.now(),
            )
            return Result(ok=True, data={"proposed": proposal.id, "content": proposal.content})
        try:
            memory = await asyncio.to_thread(
                memories.store.remember,
                actor,
                scope=scope,
                subject_id=subject,
                guild_id=context.guild_id,
                content=content,
                source="explicit",
                now=memories.now(),
            )
        except (MemoryDenied, ValueError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        return Result(ok=True, data={"id": memory.id, "content": memory.content})

    return run


def _search(memories: Memories) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        hits = await asyncio.to_thread(
            memories.store.search,
            str(args.get("query") or ""),
            user_id=context.user_id,
            guild_id=context.guild_id,
        )
        await asyncio.to_thread(
            memories.store.mark_used,
            tuple(item.id for item in hits),
            memories.now(),
        )
        return Result(
            ok=True,
            data={"memories": [{"id": item.id, "content": item.content} for item in hits]},
        )

    return run


def _forget(memories: Memories) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        try:
            removed = await asyncio.to_thread(
                memories.store.forget,
                _actor(context),
                int(args["id"]),
                memories.now(),
            )
        except MemoryDenied as exc:
            return Result(ok=False, data={}, error=str(exc))
        if not removed:
            return Result(ok=False, data={}, error="Souvenir introuvable.")
        return Result(ok=True, data={"id": int(args["id"])})

    return run


def _actor(context: Context) -> Actor:
    return Actor(context.user_id, context.is_owner, context.is_moderator)


def _subject(scope: str, context: Context) -> int:
    if scope == "self":
        return 0
    if scope == "guild":
        return context.guild_id or 0
    return context.user_id


def _remember_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "scope": {"type": "string", "enum": ["user", "guild", "self"]},
        },
        "required": ["content"],
    }


def _query_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
