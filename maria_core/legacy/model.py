"""Ce que l'import est prêt à écrire, et ce qu'il laisse de côté."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Skip:
    source: str
    legacy_id: str
    reason: str
    loud: bool = True


@dataclass(frozen=True, slots=True)
class ObjectiveDraft:
    legacy_id: str
    owner_id: int
    guild_id: int | None
    channel_ids: tuple[int, ...]
    deliver: str
    title: str
    trigger: dict[str, object]
    condition: dict[str, object] | None
    action: dict[str, object]
    status: str
    next_run_at: str | None
    fires: int
    max_fires: int | None
    cooldown_s: int
    expires_at: str | None
    state: dict[str, object]
    created_at: str
    notice: str = ""
    var_key: str = ""


@dataclass(frozen=True, slots=True)
class MemoryDraft:
    legacy_id: str
    scope: str
    subject_id: int
    guild_id: int | None
    content: str
    created_by: int
    created_at: str
    chroma_id: str


@dataclass(frozen=True, slots=True)
class ProposalDraft:
    legacy_id: str
    guild_id: int | None
    subject_user_id: int | None
    scope: str
    content: str
    confidence: float | None
    created_at: str


@dataclass(frozen=True, slots=True)
class GuildDraft:
    guild_id: int
    mode: str
    notice: str = ""


@dataclass(frozen=True, slots=True)
class ChannelDraft:
    channel_id: int
    guild_id: int
    respond_everyone: int
    auto_transcribe: int


@dataclass(frozen=True, slots=True)
class EmojiDraft:
    guild_id: int
    emoji: str
    uses: int
    updated_at: str

    @property
    def legacy_id(self) -> str:
        return f"{self.guild_id}:{self.emoji}"


@dataclass(frozen=True, slots=True)
class PollDraft:
    message_id: int
    channel_id: int
    guild_id: int
    author_id: int
    question: str
    options: tuple[str, ...]
    created_at: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class ImportPlan:
    root: str
    missing_root: bool
    objectives: tuple[ObjectiveDraft, ...]
    memories: tuple[MemoryDraft, ...]
    proposals: tuple[ProposalDraft, ...]
    guilds: tuple[GuildDraft, ...]
    channels: tuple[ChannelDraft, ...]
    emojis: tuple[EmojiDraft, ...]
    polls: tuple[PollDraft, ...]
    skips: tuple[Skip, ...]
    ignored: tuple[str, ...]
    absent: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApplyResult:
    inserted: int
    already: int

    def text(self) -> str:
        return f"Écrit : {self.inserted}. Déjà présents : {self.already}."
