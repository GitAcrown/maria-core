"""Un message non adressé : score, puis éventuellement une réaction. Pas de tirage au sort."""

import asyncio
import unicodedata
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from maria_core.conversation.model import Inbound
from maria_core.db import Database
from maria_core.decisions.engine import Decider
from maria_core.social.baseline import record, threshold
from maria_core.social.levels import Level, level_for, room_budget
from maria_core.social.room import Room
from maria_core.social.score import Parts, parts_from
from maria_core.social.store import DAILY_DECISIONS, SocialStore

type Reactor = Callable[[int, int, str], Awaitable[None]]
type Clock = Callable[[], datetime]


class Social:
    def __init__(
        self,
        database: Database,
        engine: Decider | None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._clock = clock or _now
        self._database = database
        self._engine = engine
        self._store = SocialStore(database)
        self.room = Room(self._clock)
        self.reactor: Reactor | None = None

    def explain(self, message_id: int) -> str:
        return self._store.explain(message_id)

    async def note(self, message: Inbound) -> None:
        if message.author_is_bot or message.guild_id is None:
            return
        self.room.note(message.channel_id, message.author_id)
        await asyncio.to_thread(record, self._database, message.guild_id, self._clock())

    def note_addressed(self, message: Inbound) -> None:
        if message.guild_id is None:
            return
        self.room.bump_attention(message.guild_id, message.author_id)

    def note_reply(self, message: Inbound) -> None:
        self.room.bump_fatigue(message.channel_id, message.author_id)
        self.room.open_followup(message.channel_id, message.author_id)

    async def consider(self, message: Inbound) -> str:
        """Réaction ambiante. Chaîne vide si MARIA s'abstient."""
        if message.author_is_bot or message.guild_id is None or message.is_dm:
            return ""
        level = await self._level(message)
        scored = self._parts(message)
        limit = await self._threshold(message, level)
        if level.name == "off" or level.per_hour <= 0:
            await self._keep(message, scored, limit, "off")
            return ""
        if scored.total() < limit:
            await self._keep(message, scored, limit, "below")
            return ""
        hour = self._clock().strftime("%Y-%m-%dT%H")
        used, last_author = await asyncio.to_thread(
            self._store.reactions_this_hour, message.channel_id, hour
        )
        allowance = room_budget(level.per_hour, self.room.humans(message.channel_id))
        if used >= allowance:
            await self._keep(message, scored, limit, "budget")
            return ""
        if last_author == message.author_id:
            await self._keep(message, scored, limit, "same_author")
            return ""
        emojis = await asyncio.to_thread(self._store.top_emojis, message.guild_id)
        if not emojis:
            await self._keep(message, scored, limit, "no_emoji")
            return ""
        if not await self._allowed(message, "ambient_react", {"score": scored.total()}):
            await self._keep(message, scored, limit, "no")
            return ""
        emoji = await self._pick(message, emojis)
        await asyncio.to_thread(
            self._store.mark_reaction, message.channel_id, hour, message.author_id
        )
        self.room.mark_react(message.channel_id)
        await self._keep(message, scored, limit, "react", emoji)
        await self._react(message.channel_id, message.message_id, emoji)
        return emoji

    async def wants_followup(self, message: Inbound) -> bool:
        if message.guild_id is None or message.is_dm or message.author_is_bot:
            return False
        level = await self._level(message)
        if level.followup_s <= 0:
            return False
        window = self.room.followup(message.channel_id, message.author_id)
        if window is None:
            return False
        elapsed, depth = window
        if elapsed > level.followup_s or depth > level.followup_depth:
            return False
        return await self._allowed(
            message,
            "followup",
            {"text": message.text[:300], "elapsed_s": elapsed, "depth": depth, "same_author": True},
            yes="respond",
        )

    async def notice_reaction(
        self,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
        user_id: int,
        emoji: str,
    ) -> None:
        await asyncio.to_thread(self._store.learn, guild_id, emoji, self._clock())
        humans = self.room.add_human_reaction(message_id, emoji, user_id)
        if humans < 2 or self.room.joined(message_id, emoji):
            return
        level = await asyncio.to_thread(level_for, self._database, guild_id, user_id)
        if level.name == "off":
            return
        hour = self._clock().strftime("%Y-%m-%dT%H")
        used, _last = await asyncio.to_thread(self._store.reactions_this_hour, channel_id, hour)
        if used >= room_budget(level.per_hour, self.room.humans(channel_id)):
            return
        allowed = await self._join(channel_id, message_id, emoji, humans)
        if not allowed:
            return
        self.room.mark_joined(message_id, emoji)
        await asyncio.to_thread(self._store.mark_reaction, channel_id, hour, user_id)
        await self._react(channel_id, message_id, emoji)

    def _parts(self, message: Inbound) -> Parts:
        guild = message.guild_id or 0
        return parts_from(
            humans=self.room.humans(message.channel_id),
            human_reactions=0,
            expressive=_expressive(message.text),
            attention=self.room.attention(guild, message.author_id),
            fatigue=self.room.fatigue(message.channel_id, message.author_id),
            maria_reacted=self.room.reacted_recently(message.channel_id),
        )

    async def _threshold(self, message: Inbound, level: Level) -> float:
        if message.guild_id is None or level.name == "off":
            return level.threshold
        return await asyncio.to_thread(
            threshold, self._database, message.guild_id, self._clock(), level.threshold
        )

    async def _keep(
        self,
        message: Inbound,
        parts: Parts,
        limit: float,
        verdict: str,
        emoji: str = "",
    ) -> None:
        await asyncio.to_thread(
            self._store.log,
            now=self._clock(),
            guild_id=message.guild_id,
            channel_id=message.channel_id,
            message_id=message.message_id,
            author_id=message.author_id,
            parts=parts,
            threshold=limit,
            verdict=verdict,
            emoji=emoji,
        )

    async def _allowed(
        self,
        message: Inbound,
        name: str,
        state: dict[str, object],
        *,
        yes: object = True,
    ) -> bool:
        spent = await asyncio.to_thread(self._store.model_calls_today, self._clock())
        if self._engine is None or spent >= DAILY_DECISIONS:
            return False
        verdict = await self._engine.resolve(name, state)
        return verdict.value == yes

    async def _pick(self, message: Inbound, emojis: tuple[str, ...]) -> str:
        if self._engine is None or len(emojis) == 1:
            return emojis[0]
        verdict = await self._engine.resolve(
            "pick_reaction",
            {"text": message.text[:200], "options": list(emojis)},
        )
        try:
            index = int(verdict.value)
        except (TypeError, ValueError):
            index = 0
        if index < 0 or index >= len(emojis):
            return emojis[0]
        return emojis[index]

    async def _join(self, channel_id: int, message_id: int, emoji: str, humans: int) -> bool:
        if self._engine is None:
            return False
        verdict = await self._engine.resolve(
            "join_reaction",
            {"already": False, "humans": humans, "emoji": emoji, "channel_id": channel_id},
        )
        return verdict.value is True

    async def _level(self, message: Inbound) -> Level:
        return await asyncio.to_thread(
            level_for, self._database, message.guild_id or 0, message.author_id
        )

    async def _react(self, channel_id: int, message_id: int, emoji: str) -> None:
        if self.reactor is not None:
            await self.reactor(channel_id, message_id, emoji)


def _expressive(text: str) -> bool:
    if "!" in text:
        return True
    letters = [char for char in text if char.isalpha()]
    if len(letters) >= 4 and all(char.isupper() for char in letters):
        return True
    return any(unicodedata.category(char) == "So" for char in text)


def _now() -> datetime:
    return datetime.now(UTC)
