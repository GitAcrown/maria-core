"""Client de modèle scripté, pour les tests de la boucle et du service."""

from collections.abc import Mapping, Sequence
from typing import Any

from maria_core.errors import LLMError
from maria_core.llm.types import Completion, ToolChoice


class ScriptedClient:
    def __init__(self, replies: list[Completion], *, transcript: str = "salut") -> None:
        self._replies = list(replies)
        self._transcript = transcript
        self.seen: list[list[Mapping[str, Any]]] = []
        self.tools: list[Sequence[Mapping[str, Any]] | None] = []
        self.choices: list[ToolChoice] = []
        self.closed = False
        self.fail = False

    async def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: ToolChoice = "auto",
    ) -> Completion:
        if self.fail:
            raise LLMError("indisponible")
        self.seen.append([dict(message) for message in messages])
        self.tools.append(tools)
        self.choices.append(tool_choice)
        if not self._replies:
            return Completion(text="", model="fake")
        return self._replies.pop(0)

    async def transcribe(self, audio: bytes, *, filename: str) -> str:
        return self._transcript

    async def close(self) -> None:
        self.closed = True
