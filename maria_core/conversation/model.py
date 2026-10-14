"""Messages normalisés. Discord ne dépasse pas l'adaptateur."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum

from maria_core.ui.widgets import Card


class ReplyMode(StrEnum):
    OFF = "off"
    STRICT = "strict"
    GREEDY = "greedy"


class Action(StrEnum):
    IGNORE = "ignore"
    STORE = "store"
    RESPOND = "respond"
    REACT = "react"


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
    limit: str = "none"


@dataclass(frozen=True, slots=True)
class ImageRef:
    url: str


@dataclass(frozen=True, slots=True)
class AudioRef:
    """Pièce jointe audio, téléchargée seulement si on la transcrit."""

    filename: str
    size: int
    load: Callable[[], Awaitable[bytes]]
    seconds: float | None = None
    voice: bool = False


@dataclass(frozen=True, slots=True)
class FileRef:
    """Pièce jointe qui n'est ni une image ni un audio. Lue seulement si on répond."""

    filename: str
    size: int
    load: Callable[[], Awaitable[bytes]]
    content_type: str = ""


@dataclass(frozen=True, slots=True)
class Quote:
    """Message cité par un reply Discord. Ce n'est jamais le texte de l'auteur."""

    message_id: int
    author_id: int
    author_name: str
    text: str
    from_bot_self: bool
    from_bot: bool
    images: tuple[ImageRef, ...] = ()


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
    mentioned_names: tuple[tuple[int, str], ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    settings_channel_id: int | None = None
    channel_label: str = ""
    quote: Quote | None = None
    extras: tuple[str, ...] = ()
    files: tuple[FileRef, ...] = ()
    has_media: bool = False
    transcribed: bool = False

    @property
    def policy_channel_id(self) -> int:
        """Les réglages d'un thread sont ceux de son salon parent."""
        return self.settings_channel_id or self.channel_id

    def with_text(self, text: str, *, transcribed: bool = False) -> Inbound:
        return replace(self, text=text, audio=None, transcribed=transcribed)


@dataclass(frozen=True, slots=True)
class Reply:
    """Texte prêt à envoyer. `edit_message_id` désigne une réponse déjà postée."""

    chunks: tuple[str, ...]
    user_message_id: int
    edit_message_id: int | None
    reply: bool
    cards: tuple[Card, ...] = ()
    footer: str = ""
    proposal_id: int | None = None
    learned_id: int | None = None
    trace: str = ""

    @property
    def text(self) -> str:
        return "\n".join(self.chunks)
