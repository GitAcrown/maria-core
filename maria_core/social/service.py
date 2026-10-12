"""Un message non adressé : score, puis éventuellement une réaction. Pas de tirage au sort."""

import asyncio
import logging
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from maria_core.conversation.address import is_question
from maria_core.conversation.model import Inbound
from maria_core.db import Database
from maria_core.decisions.engine import Decider
from maria_core.social.baseline import record, threshold
from maria_core.social.emojis import Usable, learn, learn_text, shortlist
from maria_core.social.levels import Level, level_for, room_budget
from maria_core.social.room import ATTENTION_WARM, FATIGUE_EXHAUSTED, Room
from maria_core.social.score import Parts, parts_from
from maria_core.social.store import DAILY_DECISIONS, SocialStore

logger = logging.getLogger(__name__)

type Reactor = Callable[[int, int, str], Awaitable[bool]]
type Clock = Callable[[], datetime]

_BANDWAGON_AGE = 6 * 3600.0
_AMBIENT_COOLDOWN = 45.0
_TYPING_FACTOR = 2.5


@dataclass(frozen=True, slots=True)
class ReactionSeen:
    """Une réaction humaine, vue par l'adaptateur."""

    guild_id: int
    channel_id: int
    message_id: int
    user_id: int
    emoji: str
    author_id: int | None = None
    author_is_bot: bool = False
    age_s: float = 0.0
    excerpt: str = ""
    enabled: bool = True


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
        self.usable: Usable = _any_emoji

    def explain(self, message_id: int) -> str:
        return self._store.explain(message_id)

    async def note(self, message: Inbound) -> None:
        self.room.remember_message(
            message.message_id, message.author_id, message.author_is_bot, message.text
        )
        if message.author_is_bot or message.guild_id is None:
            return
        self.room.note(message.channel_id, message.author_id)
        now = self._clock()
        await asyncio.to_thread(record, self._database, message.guild_id, now)
        if message.text:
            await asyncio.to_thread(
                learn_text, self._database, message.guild_id, message.text, now, self.usable
            )

    def note_addressed(self, message: Inbound) -> None:
        if message.guild_id is not None:
            self.room.bump_attention(message.guild_id, message.author_id)

    def note_reply(self, message: Inbound, text: str) -> None:
        self.room.bump_fatigue(message.channel_id, message.author_id)
        self.room.open_followup(message.channel_id, message.author_id, text)

    def prefers_emoji(self, message: Inbound) -> bool:
        """Épuisée, auteur pas chaud, pas une question : un emoji au lieu d'une phrase."""
        if message.guild_id is None or is_question(message.text):
            return False
        if self.room.is_hot(message.guild_id, message.author_id):
            return False
        return self.room.fatigue(message.channel_id, message.author_id) >= FATIGUE_EXHAUSTED

    def typing(self, channel_id: int, user_id: int) -> None:
        if self.room.extend_followup(channel_id, user_id):
            logger.debug("Suivi %s : la personne écrit, fenêtre allongée", channel_id)

    async def consider(self, message: Inbound, *, enabled: bool = True) -> str:
        """Réaction ambiante. Chaîne vide si MARIA s'abstient."""
        if message.author_is_bot or message.guild_id is None or message.is_dm:
            return ""
        level = await self._level(message)
        scored = self._parts(message)
        limit = await self._threshold(message, level)
        verdict = self._gate(message, level, enabled, scored, limit)
        if verdict:
            await self._keep(message, scored, limit, verdict)
            return ""
        return await self._ambient(message, level, scored, limit)

    async def react_now(
        self, message: Inbound, target_id: int, *, fallback: str | None = None
    ) -> str:
        """Réaction voulue (demande, silence choisi, fatigue). Pas de budget."""
        emoji = ""
        if message.guild_id is not None:
            options = await asyncio.to_thread(
                shortlist, self._database, message.guild_id, message.text, self.usable
            )
            emoji = await self._pick(message.text, options) if options else ""
        emoji = emoji or (fallback or "")
        if not emoji or not await self._react(message.channel_id, target_id, emoji):
            return ""
        self.room.mark_react(message.channel_id)
        return emoji

    async def wants_followup(self, message: Inbound) -> str:
        """`respond`, `react` ou `ignore` pour un message qui suit une réponse de MARIA."""
        if message.guild_id is None or message.is_dm or message.author_is_bot:
            return "ignore"
        level = await self._level(message)
        window = self.room.followup(message.channel_id, message.author_id)
        if level.followup_s <= 0 or window is None:
            return "ignore"
        elapsed, follow = window
        tired = self.room.fatigue(message.channel_id, message.author_id) >= FATIGUE_EXHAUSTED / 1.6
        limit = level.followup_s * (_TYPING_FACTOR if follow.extended else 1.0)
        limit *= 0.6 if tired else 1.0
        if elapsed > limit or follow.depth > level.followup_depth:
            return "ignore"
        state = {
            "text": message.text[:300],
            "bot_last": follow.bot_text[:300],
            "elapsed_s": round(elapsed),
            "depth": follow.depth,
            "same_author": True,
            "question": is_question(message.text),
        }
        return await self._choice("followup", state)

    async def notice_reaction(self, seen: ReactionSeen) -> None:
        await asyncio.to_thread(
            learn, self._database, seen.guild_id, seen.emoji, seen.excerpt, self._clock()
        )
        humans = self.room.add_human_reaction(seen.message_id, seen.emoji, seen.user_id)
        if not self._can_join(seen, humans):
            return
        level = await asyncio.to_thread(level_for, self._database, seen.guild_id, seen.user_id)
        if level.name == "off":
            return
        hour = self._clock().strftime("%Y-%m-%dT%H")
        used, _last = await asyncio.to_thread(
            self._store.reactions_this_hour, seen.channel_id, hour
        )
        if used >= room_budget(level.per_hour, self.room.humans(seen.channel_id)):
            return
        if not await self._join(seen, humans):
            return
        self.room.mark_joined(seen.message_id, seen.emoji)
        await asyncio.to_thread(self._store.mark_reaction, seen.channel_id, hour, seen.user_id)
        await self._react(seen.channel_id, seen.message_id, seen.emoji)

    def _can_join(self, seen: ReactionSeen, humans: int) -> bool:
        if not seen.enabled or seen.author_is_bot or seen.age_s > _BANDWAGON_AGE:
            return False
        if self.room.joined(seen.message_id, seen.emoji):
            return False
        if humans >= 2:
            return True
        author = seen.author_id
        warmth = self.room.attention(seen.guild_id, author) if author is not None else 0.0
        return humans == 1 and warmth >= ATTENTION_WARM * 0.4

    def _gate(
        self, message: Inbound, level: Level, enabled: bool, scored: Parts, limit: float
    ) -> str:
        if not enabled or level.name == "off" or level.per_hour <= 0:
            return "off"
        if len(message.text) > 400 or not message.text.strip():
            return "length"
        if self.room.attention(message.guild_id or 0, message.author_id) < ATTENTION_WARM:
            return "cold"
        if self.room.reacted_recently(message.channel_id, _AMBIENT_COOLDOWN):
            return "cooldown"
        if scored.total() < limit:
            return "below"
        return ""

    async def _ambient(self, message: Inbound, level: Level, scored: Parts, limit: float) -> str:
        hour = self._clock().strftime("%Y-%m-%dT%H")
        used, last_author = await asyncio.to_thread(
            self._store.reactions_this_hour, message.channel_id, hour
        )
        if used >= room_budget(level.per_hour, self.room.humans(message.channel_id)):
            await self._keep(message, scored, limit, "budget")
            return ""
        if last_author == message.author_id:
            await self._keep(message, scored, limit, "same_author")
            return ""
        state = {"text": message.text[:300], "score": round(scored.total(), 2)}
        if not await self._allowed("ambient_react", state):
            await self._keep(message, scored, limit, "no")
            return ""
        emoji = await self.react_now(message, message.message_id)
        if not emoji:
            await self._keep(message, scored, limit, "no_emoji")
            return ""
        await asyncio.to_thread(
            self._store.mark_reaction, message.channel_id, hour, message.author_id
        )
        await self._keep(message, scored, limit, "react", emoji)
        return emoji

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
        self, message: Inbound, parts: Parts, limit: float, verdict: str, emoji: str = ""
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

    async def _allowed(self, name: str, state: dict[str, object], *, yes: object = True) -> bool:
        spent = await asyncio.to_thread(self._store.model_calls_today, self._clock())
        if self._engine is None or spent >= DAILY_DECISIONS:
            return False
        verdict = await self._engine.resolve(name, state)
        return verdict.value == yes

    async def _choice(self, name: str, state: dict[str, object]) -> str:
        spent = await asyncio.to_thread(self._store.model_calls_today, self._clock())
        if self._engine is None or spent >= DAILY_DECISIONS:
            return "ignore"
        verdict = await self._engine.resolve(name, state)
        return str(verdict.value)

    async def _pick(self, text: str, emojis: tuple[str, ...]) -> str:
        if self._engine is None or len(emojis) == 1:
            return emojis[0]
        verdict = await self._engine.resolve(
            "pick_reaction", {"text": text[:300], "options": list(emojis)}
        )
        try:
            index = int(verdict.value)
        except (TypeError, ValueError):
            index = 0
        return emojis[index] if 0 <= index < len(emojis) else emojis[0]

    async def _join(self, seen: ReactionSeen, humans: int) -> bool:
        if self._engine is None:
            return False
        excerpt = seen.excerpt or _excerpt(self.room, seen.message_id)
        verdict = await self._engine.resolve(
            "join_reaction",
            {"text": excerpt[:300], "humans": humans, "emoji": seen.emoji, "already": False},
        )
        return verdict.value is True

    async def _level(self, message: Inbound) -> Level:
        return await asyncio.to_thread(
            level_for, self._database, message.guild_id or 0, message.author_id
        )

    async def _react(self, channel_id: int, message_id: int, emoji: str) -> bool:
        if self.reactor is None:
            return False
        return await self.reactor(channel_id, message_id, emoji)


def _excerpt(room: Room, message_id: int) -> str:
    seen = room.message(message_id)
    return seen.text if seen is not None else ""


def _expressive(text: str) -> bool:
    if "!" in text:
        return True
    letters = [char for char in text if char.isalpha()]
    if len(letters) >= 4 and all(char.isupper() for char in letters):
        return True
    return any(unicodedata.category(char) == "So" for char in text) or "<:" in text


def _any_emoji(_emoji: str) -> bool:
    return True


def _now() -> datetime:
    return datetime.now(UTC)
