"""Ce qui entre dans le prompt, et ce qui reste une proposition."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from maria_core.db import Database
from maria_core.decisions.engine import Decider
from maria_core.memory.model import Memory, MemoryAsk
from maria_core.memory.policy import Actor
from maria_core.memory.store import MemoryStore
from maria_core.memory.text import explicit_fact, proposal_fact
from maria_core.vectors.index import VectorIndex

type Clock = Callable[[], datetime]


class Memories:
    def __init__(
        self,
        database: Database,
        index: VectorIndex,
        *,
        engine: Decider | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.store = MemoryStore(database, index)
        self._index = index
        self._database = database
        self._engine = engine
        self._clock = clock or _now

    def now(self) -> datetime:
        return self._clock()

    def context_for(
        self,
        user_id: int,
        guild_id: int | None,
        text: str,
        mentioned: tuple[int, ...] = (),
    ) -> str:
        now = self.now()
        self.store.maintain(now)
        found = list(self.store.profile(user_id, limit=3))
        for person in mentioned[:3]:
            found.extend(self.store.profile(person, limit=2))
        found.extend(
            self.store.search(
                text, user_id=user_id, guild_id=guild_id, mentioned=mentioned, limit=4
            )
        )
        found.extend(self._vector_hits(text, user_id, guild_id, mentioned))
        unique = _unique(found)[:8]
        self.store.mark_used(tuple(item.id for item in unique), now)
        if not unique:
            return ""
        lines = [f"- ({item.scope}) {item.content}" for item in unique]
        return "Souvenirs utiles :\n" + "\n".join(lines)

    async def observe(
        self,
        *,
        author_id: int,
        guild_id: int | None,
        channel_id: int,
        message_id: int,
        text: str,
        is_owner: bool,
        is_moderator: bool,
    ) -> MemoryAsk | None:
        """Appelé seulement pour un échange adressé à MARIA."""
        now = self.now()
        actor = Actor(author_id, is_owner, is_moderator)
        await asyncio.to_thread(self.store.maintain, now)
        fact = explicit_fact(text)
        if fact:
            await asyncio.to_thread(
                self.store.remember,
                actor,
                scope="user",
                subject_id=author_id,
                guild_id=guild_id,
                content=fact,
                source="explicit",
                now=now,
            )
            return None
        if await asyncio.to_thread(self.store.confirm_repeat, actor, text, now):
            return None
        fact = proposal_fact(text)
        if not fact or not await self._worth(fact):
            return None
        if await asyncio.to_thread(self.store.asked_recently, author_id, now):
            return None
        proposal = await asyncio.to_thread(
            self.store.propose,
            scope="user",
            content=fact,
            subject_user_id=author_id,
            guild_id=guild_id,
            channel_id=channel_id,
            source_message_id=message_id,
            now=now,
        )
        enabled = await asyncio.to_thread(self._prompts_enabled, author_id, guild_id)
        if not enabled:
            return None
        return MemoryAsk(proposal.id, f"Je note que {proposal.content} ?")

    async def _worth(self, text: str) -> bool:
        if self._engine is None:
            return False
        verdict = await self._engine.resolve("memory_worth_proposing", {"text": text[:500]})
        return verdict.value is True

    def _prompts_enabled(self, user_id: int, guild_id: int | None) -> bool:
        if guild_id is None:
            return True
        row = self._database.fetchone(
            """
            SELECT memory_prompts FROM member_settings
            WHERE user_id = ? AND guild_id = ?
            """,
            (user_id, guild_id),
        )
        if row is None:
            return True
        return int(row["memory_prompts"]) == 1

    def _vector_hits(
        self,
        text: str,
        user_id: int,
        guild_id: int | None,
        mentioned: tuple[int, ...],
    ) -> list[Memory]:
        hits: list[Memory] = []
        for memory_id in self._index.search(text, limit=4):
            memory = self.store.get(memory_id)
            if memory is None or memory.deleted_at is not None:
                continue
            if _keeps(memory, user_id, guild_id, mentioned):
                hits.append(memory)
        return hits


def render_moi(memories: tuple[Memory, ...], proposals: tuple[object, ...]) -> str:
    lines = ["Tes souvenirs :"]
    if memories:
        lines.extend(f"- #{item.id} {item.content}" for item in memories)
    else:
        lines.append("- aucun")
    lines.append("Propositions :")
    if proposals:
        lines.extend(
            f"- #{item.id} {item.content}" for item in proposals if hasattr(item, "content")
        )
    else:
        lines.append("- aucune")
    return "\n".join(lines)


def _unique(items: list[Memory]) -> list[Memory]:
    seen: set[int] = set()
    ordered: list[Memory] = []
    for item in items:
        if item.id in seen or item.deleted_at is not None:
            continue
        seen.add(item.id)
        ordered.append(item)
    return ordered


def _keeps(memory: Memory, user_id: int, guild_id: int | None, mentioned: tuple[int, ...]) -> bool:
    if memory.scope == "self":
        return True
    if memory.scope == "guild":
        return guild_id is not None and memory.guild_id == guild_id
    return memory.subject_id in {user_id, *mentioned}


def _now() -> datetime:
    return datetime.now(UTC)
