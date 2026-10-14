"""Messages d'un salon sur une fenêtre, pour un résumé. Un gros fil est pré-résumé par lots."""

import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from maria_core.capabilities.base import Capability, Context, Result, Risk
from maria_core.capabilities.ports import ChannelReader, HistoryWindow

type Lines = Callable[[int], tuple[str, ...]]
type Reader = Callable[[], ChannelReader | None]
type Condense = Callable[[str, str], Awaitable[str]]
type Away = Callable[[int, int], datetime | None]

PARIS = ZoneInfo("Europe/Paris")
DEFAULT_LIMIT = 250
MAX_LIMIT = 500
_DIRECT_CHARS = 18_000
_CHUNK_CHARS = 18_000
_CLOCK = re.compile(r"^\s*(\d{1,2})(?:[:h](\d{2})?)?\s*$", re.IGNORECASE)

_DESCRIPTION = (
    "Lit les messages d'un salon pour que tu les résumes. « résume le salon » : rien d'autre. "
    '« depuis 16h » : since="16:00" (une heure, pas une durée). « aujourd\'hui » : '
    'since="00:00". « les 3 dernières heures » : hours=3. Une demande précise (« ce qu\'a dit '
    "X », « les décisions ») va dans focus. channel_id pour un autre salon. Résume ensuite "
    "en restant fidèle aux messages, sans rien inventer. « ce que j'ai raté », « qu'est-ce qui "
    "s'est dit pendant que j'étais parti » : missed=true (depuis son dernier départ du salon, "
    "sans qu'il ait à préciser de durée)."
)


def summary_capability(
    transcript: Lines,
    reader: Reader,
    condense: Condense | None = None,
    away: Away | None = None,
) -> Capability:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        channel_id = _channel(args, context)
        now = datetime.now(UTC)
        try:
            window = window_of(args, now)
            if args.get("missed") is True:
                left = away(context.user_id, channel_id) if away is not None else None
                window = missed_window(left, now)
        except ValueError as exc:
            return Result(ok=False, data={}, error=str(exc))
        lines = await _lines(context, channel_id, window, reader, transcript)
        if isinstance(lines, str):
            return Result(ok=False, data={}, error=lines)
        if not lines:
            return Result(ok=False, data={}, error="Aucun message utile dans cette fenêtre.")
        focus = str(args.get("focus") or "").strip()
        data: dict[str, Any] = {"count": len(lines), "window": window.label, "focus": focus}
        blob = "\n".join(lines)
        if len(blob) <= _DIRECT_CHARS or condense is None:
            data["messages"] = list(lines)[-window.limit :]
        else:
            data["partial_summaries"] = await _condensed(lines, focus, condense)
        return Result(ok=True, data=data)

    return Capability(
        name="summarize_channel",
        description=_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "channel_id": {"type": "string", "description": "Autre salon (défaut : celui-ci)"},
                "since": {"type": "string", "description": "Heure de Paris HH:MM"},
                "hours": {"type": "number", "minimum": 0.25, "maximum": 72},
                "limit": {"type": "integer", "minimum": 5, "maximum": MAX_LIMIT},
                "focus": {"type": "string", "description": "Ce qu'il faut en tirer"},
                "missed": {
                    "type": "boolean",
                    "description": "true : depuis le dernier départ de la personne du salon",
                },
            },
            "required": [],
        },
        risk=Risk.READ,
        run=run,
        timeout_s=90,
    )


def window_of(args: Mapping[str, Any], now: datetime) -> HistoryWindow:
    limit = _limit(args.get("limit"))
    since = str(args.get("since") or "").strip()
    if since:
        moment = last_clock(since, now)
        return HistoryWindow(after=moment, limit=MAX_LIMIT, label=f"depuis {_hhmm(moment)}")
    hours = args.get("hours")
    if isinstance(hours, int | float) and not isinstance(hours, bool) and hours > 0:
        after = now - timedelta(hours=min(float(hours), 72.0))
        return HistoryWindow(after=after, limit=MAX_LIMIT, label=f"{hours:g} dernières heures")
    return HistoryWindow(after=None, limit=limit, label=f"{limit} derniers messages")


def missed_window(left: datetime | None, now: datetime) -> HistoryWindow:
    """Depuis que la personne a quitté le salon, au plus 72 h. Rien à dire si elle était là."""
    if left is None:
        raise ValueError(
            "Aucune trace de la dernière visite de la personne dans ce salon : demande-lui "
            "depuis quand résumer."
        )
    if now - left > timedelta(hours=72):
        left = now - timedelta(hours=72)
    if now - left < timedelta(minutes=10):
        raise ValueError("La personne était là il y a quelques minutes : rien à rattraper.")
    label = f"depuis ton dernier passage ({_hhmm(left)}, {left.astimezone(PARIS):%d/%m})"
    return HistoryWindow(after=left, limit=MAX_LIMIT, label=label)


def last_clock(raw: str, now: datetime) -> datetime:
    """« 16:00 » : la dernière fois qu'il était 16 h à Paris (hier si c'est plus tard)."""
    match = _CLOCK.match(raw)
    if match is None:
        raise ValueError(f"Heure illisible : {raw}. Format attendu : 16:00.")
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if hour > 23 or minute > 59:
        raise ValueError(f"Heure hors limites : {raw}.")
    local = now.astimezone(PARIS)
    moment = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if moment > local:
        moment -= timedelta(days=1)
    return moment.astimezone(UTC)


async def _lines(
    context: Context,
    channel_id: int,
    window: HistoryWindow,
    reader: Reader,
    transcript: Lines,
) -> tuple[str, ...] | str:
    live = reader()
    if live is not None:
        return await live.history(
            channel_id, window, user_id=context.user_id, guild_id=context.guild_id
        )
    if channel_id != context.channel_id:
        return "Lecture d'un autre salon indisponible."
    return transcript(channel_id)[-window.limit :]


async def _condensed(lines: tuple[str, ...], focus: str, condense: Condense) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) > _CHUNK_CHARS:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return [await condense(chunk, focus) for chunk in chunks[:12]]


def _channel(args: Mapping[str, Any], context: Context) -> int:
    raw = str(args.get("channel_id") or "").strip().strip("<#>")
    return int(raw) if raw.isdigit() else context.channel_id


def _limit(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return DEFAULT_LIMIT
    return min(MAX_LIMIT, max(5, raw))


def _hhmm(moment: datetime) -> str:
    return moment.astimezone(PARIS).strftime("%H:%M")
