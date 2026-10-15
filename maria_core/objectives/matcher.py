"""Relie un événement aux objectifs qui l'écoutent : salon, auteur, mot ou sujet, vocal."""

import asyncio
import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from maria_core.objectives.model import Objective
from maria_core.objectives.runner import Runner
from maria_core.objectives.signals import ObjectiveSignal
from maria_core.objectives.store import ObjectiveStore

logger = logging.getLogger(__name__)

type Relevance = Callable[[str, Mapping[str, Any]], Awaitable[bool]]

_VOICE = {"voice_join": "join", "voice_leave": "leave", "voice_stream": "stream"}


class Matcher:
    def __init__(self, store: ObjectiveStore, runner: Runner) -> None:
        self._store = store
        self._runner = runner
        self.relevance: Relevance | None = None

    async def handle(self, signal: ObjectiveSignal, *, now: datetime) -> int:
        if signal.author_is_bot:
            return 0
        fired = 0
        for objective in await asyncio.to_thread(self._store.event_objectives):
            if not matches(objective, signal) or _cooling(objective, now):
                continue
            if not await self._relevant(objective, signal):
                continue
            try:
                outcome = await self._runner.execute(objective, key=signal.key, signal=signal)
            except Exception:
                logger.exception("Écoute %s en échec", objective.id)
                continue
            fired += outcome == "sent"
        return fired

    async def _relevant(self, objective: Objective, signal: ObjectiveSignal) -> bool:
        """Le mot ne suffit pas : JEV vérifie que le message parle bien du sujet voulu.

        Sans juge disponible, le mot (ou la phrase) cité suffit.
        """
        trigger = objective.trigger
        if str(trigger.get("type")) != "on_topic" or self.relevance is None:
            return True
        topic = str(trigger.get("topic") or "")
        if topic:
            return await self.relevance("topic_match", {"topic": topic, "message": signal.text})
        pattern = str(trigger.get("pattern") or "")
        return await self.relevance(
            "listen_relevance", {"pattern": pattern, "message": signal.text[:500]}
        )


def matches(objective: Objective, signal: ObjectiveSignal) -> bool:
    if objective.guild_id is not None and objective.guild_id != signal.guild_id:
        return False
    trigger = objective.trigger
    kind = str(trigger.get("type") or "")
    if kind == "on_voice":
        return _voice(trigger, signal)
    if kind == "on_member_join":
        return signal.kind == "join"
    if objective.channel_ids and signal.channel_id not in objective.channel_ids:
        return False
    test = _TESTS.get(kind)
    if test is None or signal.kind not in _KINDS.get(kind, {"message"}):
        return False
    if kind != "on_post" and not _author_ok(objective, signal):
        return False
    return test(objective, signal)


def _mentions(objective: Objective, signal: ObjectiveSignal) -> bool:
    target = objective.trigger.get("user_id")
    return (target if isinstance(target, int) else objective.owner_id) in signal.mentioned_ids


def _posted_by(objective: Objective, signal: ObjectiveSignal) -> bool:
    return objective.trigger.get("user_id") == signal.user_id


def _link(objective: Objective, signal: ObjectiveSignal) -> bool:
    wanted = _fold(str(objective.trigger.get("pattern") or "")).strip()
    return signal.has_link and (not wanted or wanted in _fold(signal.text))


def _attachment(objective: Objective, signal: ObjectiveSignal) -> bool:
    wanted = str(objective.trigger.get("media") or "")
    return bool(signal.media) and (not wanted or wanted in signal.media)


def _reaction(objective: Objective, signal: ObjectiveSignal) -> bool:
    wanted = str(objective.trigger.get("emoji") or "").strip()
    return bool(wanted) and wanted in {signal.emoji, f":{signal.emoji_name}:", signal.emoji_name}


_TESTS: dict[str, Callable[[Objective, ObjectiveSignal], bool]] = {
    "on_reply_to": lambda _objective, signal: signal.reply_to_bot,
    "on_topic": lambda objective, signal: _words_match(objective.trigger, signal.text),
    "on_mention": _mentions,
    "on_post": _posted_by,
    "on_link": _link,
    "on_attachment": _attachment,
    "on_reaction": _reaction,
}
_KINDS = {"on_reaction": {"reaction"}}


def word_in(text: str, term: str) -> bool:
    """Mot entier, sans tenir compte des accents ni de la casse : « vente » ≠ « aventure »."""
    folded = _fold(term).strip()
    if not folded:
        return False
    return re.search(rf"(?<!\w){re.escape(folded)}(?!\w)", _fold(text)) is not None


def _words_match(trigger: Mapping[str, Any], text: str) -> bool:
    terms = [
        str(trigger.get("pattern") or ""),
        *[str(item) for item in trigger.get("aliases") or []],
    ]
    terms = [term for term in terms if term.strip()]
    if not terms:
        return bool(trigger.get("topic")) and len(text.split()) >= 3
    return any(word_in(text, term) for term in terms)


def _voice(trigger: Mapping[str, Any], signal: ObjectiveSignal) -> bool:
    if _VOICE.get(signal.kind) != str(trigger.get("signal") or "join"):
        return False
    target = trigger.get("user_id")
    if isinstance(target, int) and target != signal.user_id:
        return False
    place = trigger.get("voice_channel_id")
    return not (isinstance(place, int) and place != signal.channel_id)


def _author_ok(objective: Objective, signal: ObjectiveSignal) -> bool:
    mode = str(objective.trigger.get("author") or "others")
    if mode == "any":
        return True
    if mode == "self":
        return signal.user_id == objective.owner_id
    if mode.isdigit():
        return signal.user_id == int(mode)
    return signal.user_id != objective.owner_id


def _cooling(objective: Objective, now: datetime) -> bool:
    if objective.cooldown_s <= 0:
        return False
    raw = objective.state.get("last_fire_at")
    if not isinstance(raw, str):
        return False
    last = datetime.fromisoformat(raw)
    if last.tzinfo is None:
        return False
    return now - last < timedelta(seconds=objective.cooldown_s)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()
