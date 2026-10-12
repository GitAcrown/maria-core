"""Client OpenAI. Seul ce module importe le SDK."""

import io
import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

import openai
from openai import AsyncOpenAI

from maria_core.errors import LLMError
from maria_core.llm.types import Completion, ToolCall, ToolChoice

logger = logging.getLogger(__name__)

MODEL_MAIN = "gpt-6-luna"
MODEL_FALLBACK = "gpt-5.6-luna"
MODEL_TRANSCRIBE = "gpt-4o-transcribe"
_TIMEOUT_SECONDS = 60.0
_RETRIES = 2
_TRANSCRIBE_PROMPT = (
    "Discord voice message. The speaker uses French or English only. "
    "Transcribe faithfully in the spoken language. "
    "Bonjour, salut, ouais. Hello, yeah, thanks."
)


class OpenAIChatClient:
    """Complétion et transcription. Le client HTTP n'est ouvert qu'au premier appel."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = MODEL_MAIN,
        fallback_model: str = MODEL_FALLBACK,
        transcription_model: str = MODEL_TRANSCRIBE,
        max_tokens: int = 1024,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._fallback = fallback_model
        self._transcription_model = transcription_model
        self._max_tokens = max_tokens
        self._client: AsyncOpenAI | None = None

    @property
    def model_name(self) -> str:
        return self._model

    async def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: ToolChoice = "auto",
    ) -> Completion:
        kwargs = self._request(messages, tools=tools, tool_choice=tool_choice, model=self._model)
        try:
            response = await self._send(kwargs)
        except openai.AuthenticationError as exc:
            response = await self._retry_with_fallback(kwargs, exc)
        except openai.OpenAIError as exc:
            raise LLMError(str(exc)) from exc
        return _completion(response)

    async def transcribe(self, audio: bytes, *, filename: str) -> str:
        audio_file = io.BytesIO(audio)
        audio_file.name = filename or "audio.ogg"
        try:
            result = await self._openai().audio.transcriptions.create(
                model=self._transcription_model,
                file=audio_file,
                prompt=_TRANSCRIBE_PROMPT,
            )
        except openai.OpenAIError as exc:
            raise LLMError(str(exc)) from exc
        return result.text or ""

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    def _request(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None,
        tool_choice: ToolChoice,
        model: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [dict(message) for message in messages],
            "max_completion_tokens": self._max_tokens,
            "reasoning_effort": "none",
        }
        if tools:
            payload["tools"] = [dict(tool) for tool in tools]
            payload["tool_choice"] = tool_choice
            if tool_choice != "none":
                payload["parallel_tool_calls"] = True
        return payload

    async def _retry_with_fallback(
        self,
        payload: dict[str, Any],
        exc: openai.AuthenticationError,
    ) -> Any:
        if payload["model"] == self._fallback:
            raise LLMError(str(exc)) from exc
        logger.error("Modèle %s refusé, repli %s", payload["model"], self._fallback)
        payload["model"] = self._fallback
        try:
            return await self._send(payload)
        except openai.OpenAIError as second:
            raise LLMError(str(second)) from second

    async def _send(self, payload: dict[str, Any]) -> Any:
        return await self._openai().chat.completions.create(**payload)

    def _openai(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                timeout=_TIMEOUT_SECONDS,
                max_retries=_RETRIES,
            )
        return self._client


def _completion(response: Any) -> Completion:
    if not response.choices:
        return Completion(text="", model=getattr(response, "model", "") or "")
    message = response.choices[0].message
    usage = response.usage
    return Completion(
        text=message.content or "",
        tool_calls=_tool_calls(message),
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        model=getattr(response, "model", "") or "",
    )


def _tool_calls(message: Any) -> tuple[ToolCall, ...]:
    calls: list[ToolCall] = []
    for item in message.tool_calls or []:
        arguments = _arguments(item.function.arguments)
        calls.append(ToolCall(id=item.id, name=item.function.name, arguments=arguments))
    return tuple(calls)


def _arguments(raw: str | None) -> dict[str, Any]:
    try:
        loaded = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {"value": loaded}
