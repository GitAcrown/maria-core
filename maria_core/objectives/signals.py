"""Événement publié par Discord. Le moteur ne connaît pas les messages Discord."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ObjectiveSignal:
    kind: str
    key: str
    channel_id: int
    guild_id: int | None
    user_id: int
    text: str = ""
    reply_to_bot: bool = False
