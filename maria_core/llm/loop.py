"""Boucle d'un tour : le modèle répond, ou appelle des outils, jusqu'à six fois."""

import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from maria_core.capabilities import Result
from maria_core.llm.types import ChatClient, Completion, ToolCall, ToolChoice

logger = logging.getLogger(__name__)

MAX_TOOL_TURNS = 6
MAX_TOOL_CALLS = 8
_NUDGE = "[SYSTEM] Réponds maintenant, en une réponse finale."

type ToolExecutor = Callable[[ToolCall], Awaitable[Result]]


@dataclass(frozen=True, slots=True)
class ToolRecord:
    name: str
    arguments: Mapping[str, Any]
    result: Result


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
    records: tuple[ToolRecord, ...] = ()
    error: str = ""


@dataclass(slots=True)
class _Turn:
    messages: list[dict[str, Any]]
    records: list[ToolRecord]
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    text: str = ""
    calls: int = 0
    error: str = ""
    nudged: bool = False


async def complete_turn(
    client: ChatClient,
    history: Sequence[Mapping[str, Any]],
    *,
    system: str,
    tools: Sequence[Mapping[str, Any]],
    execute: ToolExecutor,
    max_turns: int = MAX_TOOL_TURNS,
    first_choice: ToolChoice = "auto",
) -> LoopResult:
    turn = _Turn(messages=[{"role": "system", "content": system}], records=[])
    turn.messages.extend(dict(item) for item in history)
    started = perf_counter()
    ok = True
    for index in range(max_turns):
        allow_tools = bool(tools) and index < max_turns - 1
        choice: ToolChoice = "none" if not allow_tools else first_choice if index == 0 else "auto"
        completion = await _ask(client, turn, tools, choice)
        if completion is None:
            ok = False
            break
        if completion.tool_calls and allow_tools:
            await _run_tools(turn, completion, execute)
            continue
        if turn.text or turn.records or turn.nudged or index + 1 >= max_turns:
            break
        turn.nudged = True
        turn.messages.append({"role": "user", "content": _NUDGE})
    return _result(turn, ok, started)


async def _ask(
    client: ChatClient,
    turn: _Turn,
    tools: Sequence[Mapping[str, Any]],
    choice: ToolChoice,
) -> Completion | None:
    turn.calls += 1
    try:
        completion = await client.complete(turn.messages, tools=tools or None, tool_choice=choice)
    except Exception as exc:
        logger.exception("Complétion échouée")
        turn.error = str(exc)
        return None
    turn.input_tokens += completion.input_tokens
    turn.output_tokens += completion.output_tokens
    turn.model = completion.model or turn.model
    turn.text = completion.text.strip()
    return completion


async def _run_tools(turn: _Turn, completion: Completion, execute: ToolExecutor) -> None:
    turn.messages.append(_assistant_message(completion))
    for call in completion.tool_calls:
        result = await _run_tool(execute, call, len(turn.records))
        turn.records.append(ToolRecord(call.name, dict(call.arguments), result))
        turn.messages.append(_tool_message(call, result))


def _result(turn: _Turn, ok: bool, started: float) -> LoopResult:
    widgets = tuple(
        (record.result.widget, dict(record.result.data))
        for record in turn.records
        if record.result.ok and record.result.widget
    )
    return LoopResult(
        text=turn.text,
        tool_names=tuple(record.name for record in turn.records),
        calls=turn.calls,
        input_tokens=turn.input_tokens,
        output_tokens=turn.output_tokens,
        model=turn.model,
        duration_ms=int((perf_counter() - started) * 1000),
        ok=ok,
        widgets=widgets,
        records=tuple(turn.records),
        error=turn.error,
    )


async def _run_tool(execute: ToolExecutor, call: ToolCall, used: int) -> Result:
    if used >= MAX_TOOL_CALLS:
        return Result(ok=False, data={}, error="Plafond d'outils atteint pour ce message.")
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
        "content": json.dumps(payload, ensure_ascii=False, default=str)[:24_000],
    }
