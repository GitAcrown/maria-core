"""Sous-titres YouTube. On lit le texte, pas l'image ni le son."""

import json
import re
from collections.abc import Mapping
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlparse

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.plugins import PluginHost
from maria_core.ui.emojis import YOUTUBE
from maria_core.ui.widgets import Rendered, card, thumbnail

_OEMBED = "https://www.youtube.com/oembed"
_LANGS = ("fr", "fr-FR", "en", "en-US")
_ID = re.compile(r"^[\w-]{11}$")
_TRANSCRIPT = 8000


NAME = "youtube"


def setup(app: PluginHost) -> None:
    app.capabilities.register(youtube_capability(app.http))
    app.widgets.register("read_youtube", render_youtube)


def youtube_capability(http: HttpClient) -> Capability:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        video = video_id(str(args.get("url") or ""))
        if video is None:
            return Result(ok=False, data={}, error="Lien YouTube invalide.")
        try:
            card = await _load(http, video)
        except (ValueError, HttpError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        return Result(ok=True, data=card, widget="read_youtube")

    return Capability(
        name="read_youtube",
        description=(
            "Lit les sous-titres d'une vidéo YouTube (watch, youtu.be, shorts ou id). "
            "Ce n'est pas regarder l'image. S'il n'y a pas de sous-titres, dis-le."
        ),
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        risk=Risk.EXTERNAL,
        run=run,
    )


def render_youtube(data: Mapping[str, Any]) -> Rendered:
    video = str(data.get("video_id") or "")
    title = str(data.get("title") or video)
    if not video:
        return Rendered()
    url = f"https://www.youtube.com/watch?v={video}"
    lines = [f"## {YOUTUBE} {title}"]
    if data.get("author"):
        lines.append(f"**{data['author']}**")
    meta: list[str] = []
    seconds = data.get("seconds")
    if isinstance(seconds, int) and seconds > 0:
        meta.append(_clock(seconds))
    captions = "Sous-titres auto" if data.get("generated") else "Sous-titres"
    meta.append(f"{captions} · {data['language']}" if data.get("language") else captions)
    if data.get("truncated"):
        meta.append("transcription tronquée")
    meta.append(f"[YouTube](<{url}>)")
    lines.append(f"-# {' · '.join(meta)}")
    built = card(thumbnail("\n".join(lines), f"https://i.ytimg.com/vi/{video}/hqdefault.jpg"))
    return Rendered(cards=(built,), note=f"Vidéo lue : {title} — {data.get('author', '')}")


def _clock(seconds: int) -> str:
    hours, rest = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def video_id(raw: str) -> str | None:
    text = raw.strip()
    if _ID.fullmatch(text):
        return text
    parsed = urlparse(text)
    host = (parsed.hostname or "").removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
        return candidate if _ID.fullmatch(candidate) else None
    if host.endswith("youtube.com"):
        return _from_path(parsed.path, parsed.query)
    return None


async def _load(http: HttpClient, video: str) -> dict[str, str]:
    meta = await _oembed(http, video)
    page = await http.request(
        "GET",
        f"https://www.youtube.com/watch?v={video}",
        timeout=15,
        max_bytes=2_000_000,
    )
    if page.status != 200:
        raise ValueError("Vidéo inaccessible.")
    html = page.body.decode("utf-8", errors="replace")
    url, language, generated = _caption_url(_array_after(html, '"captionTracks":'))
    if not url:
        raise ValueError("Aucun sous-titre disponible.")
    track = await http.request("GET", url, timeout=15, max_bytes=1_000_000)
    transcript = _transcript(track.body.decode("utf-8", errors="replace"))
    if not transcript:
        raise ValueError("Sous-titres vides.")
    length = re.search(r'"lengthSeconds":"(\d+)"', html)
    return {
        "video_id": video,
        "title": meta.get("title", ""),
        "author": meta.get("author_name", ""),
        "language": language,
        "generated": generated,
        "seconds": int(length.group(1)) if length else 0,
        "truncated": len(transcript) > _TRANSCRIPT,
        "transcript": transcript[:_TRANSCRIPT],
    }


async def _oembed(http: HttpClient, video: str) -> dict[str, Any]:
    response = await http.request(
        "GET",
        with_query(_OEMBED, {"url": f"https://www.youtube.com/watch?v={video}", "format": "json"}),
    )
    try:
        payload = parse_json(response)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _from_path(path: str, query: str) -> str | None:
    if path == "/watch":
        candidate = parse_qs(query).get("v", [""])[0]
        return candidate if _ID.fullmatch(candidate) else None
    for prefix in ("/shorts/", "/embed/", "/live/"):
        if path.startswith(prefix):
            candidate = path[len(prefix) :].split("/")[0]
            return candidate if _ID.fullmatch(candidate) else None
    return None


def _array_after(html: str, marker: str) -> list[Any]:
    start = html.find(marker)
    if start < 0:
        return []
    start = html.find("[", start)
    if start < 0:
        return []
    depth = 0
    for index, char in enumerate(html[start:], start):
        depth += (char == "[") - (char == "]")
        if depth == 0:
            return _loads(html[start : index + 1])
    return []


def _loads(raw: str) -> list[Any]:
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def _caption_url(tracks: list[Any]) -> tuple[str, str, bool]:
    """(URL, langue, générée automatiquement). En français si possible."""
    found: dict[str, tuple[str, bool]] = {}
    for track in tracks:
        if isinstance(track, dict) and str(track.get("baseUrl") or "").startswith("http"):
            code = str(track.get("languageCode") or "")
            found.setdefault(code, (str(track["baseUrl"]), track.get("kind") == "asr"))
    for code in (*_LANGS, *found):
        if code in found:
            url, generated = found[code]
            return url, code, generated
    return "", "", False


def _transcript(xml: str) -> str:
    parts = [
        unescape(re.sub(r"<[^>]+>", "", piece))
        for piece in re.findall(r"<text[^>]*>(.*?)</text>", xml)
    ]
    return " ".join(part.strip() for part in parts if part.strip())
