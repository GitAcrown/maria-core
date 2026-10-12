"""Échanges avec le modèle, sans SDK."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

type ToolChoice = Literal["auto", "none", "required"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class ChatClient(Protocol):
    async def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: ToolChoice = "auto",
    ) -> Completion: ...

    async def transcribe(self, audio: bytes, *, filename: str) -> str: ...

    async def close(self) -> None: ...
