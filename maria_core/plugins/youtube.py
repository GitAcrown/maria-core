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
from maria_core.ui.widgets import Rendered, card, heading, links, thumbnail

_OEMBED = "https://www.youtube.com/oembed"
_LANGS = ("fr", "fr-FR", "en", "en-US")
_ID = re.compile(r"^[\w-]{11}$")


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
    built = card(
        heading(f"▶️ {title}", str(data.get("author") or "")),
        thumbnail("Sous-titres lus.", f"https://i.ytimg.com/vi/{video}/hqdefault.jpg"),
        links([("Voir sur YouTube", url)]),
        accent=0xFF0000,
    )
    return Rendered(cards=(built,), note=f"Vidéo lue : {title} — {data.get('author', '')}")


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
    url = _caption_url(_array_after(html, '"captionTracks":'))
    if not url:
        raise ValueError("Aucun sous-titre disponible.")
    track = await http.request("GET", url, timeout=15, max_bytes=1_000_000)
    transcript = _transcript(track.body.decode("utf-8", errors="replace"))
    if not transcript:
        raise ValueError("Sous-titres vides.")
    return {
        "video_id": video,
        "title": meta.get("title", ""),
        "author": meta.get("author_name", ""),
        "transcript": transcript[:8000],
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


def _caption_url(tracks: list[Any]) -> str:
    found: dict[str, str] = {}
    for track in tracks:
        if isinstance(track, dict) and str(track.get("baseUrl") or "").startswith("http"):
            found.setdefault(str(track.get("languageCode") or ""), str(track["baseUrl"]))
    for code in _LANGS:
        if code in found:
            return found[code]
    return next(iter(found.values()), "")


def _transcript(xml: str) -> str:
    parts = [
        unescape(re.sub(r"<[^>]+>", "", piece))
        for piece in re.findall(r"<text[^>]*>(.*?)</text>", xml)
    ]
    return " ".join(part.strip() for part in parts if part.strip())
