"""Boucle d'un tour : le modèle répond, ou appelle un outil, au plus quatre fois."""

import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from maria_core.capabilities import Result
from maria_core.llm.types import ChatClient, Completion, ToolCall

logger = logging.getLogger(__name__)

MAX_TOOL_TURNS = 4
MAX_TOOL_CALLS = 6

type ToolExecutor = Callable[[ToolCall], Awaitable[Result]]


@dataclass(frozen=True, slots=True)
class LoopResult:
    text: str
    tool_names: tuple[str, ...]
    calls: int
    input_tokens: int
    output_tokens: int
    model: str
    duration_ms: int
    ok: bool
    widgets: tuple[tuple[str, Mapping[str, Any]], ...] = ()


async def complete_turn(
    client: ChatClient,
    history: Sequence[Mapping[str, Any]],
    *,
    system: str,
    tools: Sequence[Mapping[str, Any]],
    execute: ToolExecutor,
    max_turns: int = MAX_TOOL_TURNS,
) -> LoopResult:
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    messages.extend(dict(item) for item in history)
    used: list[str] = []
    input_tokens = 0
    output_tokens = 0
    model = ""
    text = ""
    calls = 0
    widgets: list[tuple[str, Mapping[str, Any]]] = []
    started = perf_counter()
    ok = True
    for index in range(max_turns):
        calls = index + 1
        allow_tools = bool(tools) and index < max_turns - 1
        try:
            completion = await client.complete(
                messages,
                tools=tools or None,
                tool_choice="auto" if allow_tools else "none",
            )
        except Exception:
            logger.exception("Complétion échouée")
            ok = False
            break
        input_tokens += completion.input_tokens
        output_tokens += completion.output_tokens
        model = completion.model or model
        text = completion.text.strip()
        if not completion.tool_calls or not allow_tools:
            break
        messages.append(_assistant_message(completion))
        for call in completion.tool_calls:
            result = await _run_tool(execute, call, used)
            if result.ok and result.widget:
                widgets.append((result.widget, dict(result.data)))
            messages.append(_tool_message(call, result))
    elapsed = int((perf_counter() - started) * 1000)
    return LoopResult(
        text=text,
        tool_names=tuple(used),
        calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        duration_ms=elapsed,
        ok=ok,
        widgets=tuple(widgets),
    )


async def _run_tool(execute: ToolExecutor, call: ToolCall, used: list[str]) -> Result:
    if len(used) >= MAX_TOOL_CALLS:
        return Result(ok=False, data={}, error="Plafond d'outils atteint pour ce message.")
    used.append(call.name)
    return await _safe_execute(execute, call)


async def _safe_execute(execute: ToolExecutor, call: ToolCall) -> Result:
    try:
        return await execute(call)
    except Exception as exc:
        logger.exception("Outil %s en échec", call.name)
        return Result(ok=False, data={}, error=str(exc))


def _assistant_message(completion: Completion) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": completion.text or None,
        "tool_calls": [_tool_call(call) for call in completion.tool_calls],
    }


def _tool_call(call: ToolCall) -> dict[str, Any]:
    return {
        "id": call.id,
        "type": "function",
        "function": {
            "name": call.name,
            "arguments": json.dumps(dict(call.arguments), ensure_ascii=False),
        },
    }


def _tool_message(call: ToolCall, result: Result) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": result.ok, **dict(result.data)}
    if result.error:
        payload["error"] = result.error
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "content": json.dumps(payload, ensure_ascii=False, default=str),
    }
