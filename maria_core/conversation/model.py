"""Messages normalisés. Discord ne dépasse pas l'adaptateur."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum


class ReplyMode(StrEnum):
    OFF = "off"
    STRICT = "strict"
    GREEDY = "greedy"


class Action(StrEnum):
    IGNORE = "ignore"
    STORE = "store"
    RESPOND = "respond"


@dataclass(frozen=True, slots=True)
class Route:
    action: Action
    reason: str
    decision: str | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Policy:
    mode: ReplyMode
    respond_everyone: bool = False
    auto_transcribe: bool = False
    personality: str = ""


@dataclass(frozen=True, slots=True)
class ImageRef:
    url: str


@dataclass(frozen=True, slots=True)
class AudioRef:
    """Pièce jointe audio, téléchargée seulement si on la transcrit."""

    filename: str
    size: int
    load: Callable[[], Awaitable[bytes]]


@dataclass(frozen=True, slots=True)
class Inbound:
    channel_id: int
    message_id: int
    guild_id: int | None
    author_id: int
    author_name: str
    text: str
    is_dm: bool
    author_is_bot: bool
    mentioned: bool
    reply_to_bot: bool
    mention_everyone: bool
    edited: bool
    author_is_owner: bool
    author_is_moderator: bool
    bot_names: tuple[str, ...] = ()
    images: tuple[ImageRef, ...] = field(default_factory=tuple)
    audio: AudioRef | None = None
    mentioned_ids: tuple[int, ...] = ()

    def with_text(self, text: str) -> Inbound:
        return replace(self, text=text, audio=None)


@dataclass(frozen=True, slots=True)
class Reply:
    """Texte prêt à envoyer. `edit_message_id` désigne une réponse déjà postée."""

    chunks: tuple[str, ...]
    user_message_id: int
    edit_message_id: int | None
    reply: bool
    tabs: tuple[tuple[str, str], ...] = ()
    proposal_id: int | None = None
