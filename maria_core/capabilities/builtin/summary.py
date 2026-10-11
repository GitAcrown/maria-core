"""Les messages récents du salon, pour que le modèle les résume lui-même."""

from collections.abc import Callable, Mapping
from typing import Any

from maria_core.capabilities.base import Capability, Context, Result, Risk
from maria_core.capabilities.ports import ChannelReader

type Lines = Callable[[int], tuple[str, ...]]
type Reader = Callable[[], ChannelReader | None]


def summary_capability(transcript: Lines, reader: Reader) -> Capability:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        limit = _limit(args.get("limit"))
        lines = await _lines(context.channel_id, limit, reader, transcript)
        focus = str(args.get("focus") or "").strip()
        if focus:
            lines = tuple(line for line in lines if focus.casefold() in line.casefold())
        if not lines:
            return Result(ok=False, data={}, error="Aucun message récent à résumer.")
        kept = lines[-limit:]
        return Result(ok=True, data={"count": len(kept), "messages": list(kept)})

    return Capability(
        name="summarize_channel",
        description=(
            "Retourne les messages récents du salon pour que tu les résumes. "
            "Sans focus : le fil. Avec focus : seulement les lignes qui le contiennent. "
            "N'invente rien au-delà de ces messages. Défaut : le salon actuel, 40 messages."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 5, "maximum": 80},
                "focus": {"type": "string", "description": "Sujet ou pseudo à isoler"},
            },
            "required": [],
        },
        risk=Risk.READ,
        run=run,
    )


async def _lines(
    channel_id: int,
    limit: int,
    reader: Reader,
    transcript: Lines,
) -> tuple[str, ...]:
    live = reader()
    if live is not None:
        found = await live.recent(channel_id, limit)
        if found:
            return found
    return transcript(channel_id)[-limit:]


def _limit(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 40
    return min(80, max(5, raw))
