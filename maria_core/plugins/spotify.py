"""Recherche de morceau. Jeton client Spotify, mis en cache le temps de sa validité."""

import base64
import time
from collections.abc import Mapping
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.plugins import PluginHost
from maria_core.ui.emojis import MUSIC
from maria_core.ui.widgets import Rendered, card, joined, thumbnail

_TOKEN = "https://accounts.spotify.com/api/token"
_SEARCH = "https://api.spotify.com/v1/search"


NAME = "spotify"


def setup(app: PluginHost) -> None:
    capability = track_capability(
        app.http,
        app.settings.spotify_client_id,
        app.settings.spotify_client_secret,
    )
    app.capabilities.register(capability)
    app.widgets.register("search_track", render_track)


def track_capability(http: HttpClient, client_id: str, secret: str) -> Capability:
    cache = {"token": "", "until": 0.0}

    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        query = str(args["query"]).strip()
        try:
            token = await _token(http, client_id, secret, cache)
            hits = await _search(http, token, query)
        except (ValueError, HttpError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        if not hits:
            return Result(ok=False, data={}, error=f"Morceau introuvable : {query}.")
        return Result(ok=True, data={"tracks": hits}, widget="search_track")

    return Capability(
        name="search_track",
        description=(
            "Fiche Spotify d'un morceau (artiste, album, année, durée, pochette, lien). Pour "
            "identifier une chanson ou montrer un titre précis. Artiste + titre si connus."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        risk=Risk.EXTERNAL,
        cache_s=3600,
        run=run,
        requires=frozenset({"SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"}),
    )


def render_track(data: Mapping[str, Any]) -> Rendered:
    tracks = [item for item in data.get("tracks") or [] if isinstance(item, dict)]
    if not tracks:
        return Rendered()
    best = tracks[0]
    lines = [f"## {MUSIC} {best['name']}"]
    if best.get("artists"):
        lines.append(f"**{best['artists']}**")
    meta = [str(best[key]) for key in ("album", "year", "duration") if best.get(key)]
    if best.get("explicit"):
        meta.append("🅴")
    if best.get("url"):
        meta.append(f"[Spotify](<{best['url']}>)")
    if meta:
        lines.append(f"-# {joined(*meta)}")
    built = card(thumbnail("\n".join(lines), str(best.get("cover") or "")))
    return Rendered(cards=(built,), note=f"{best['artists']} — {best['name']} ({best['album']})")


async def _token(http: HttpClient, client_id: str, secret: str, cache: dict[str, Any]) -> str:
    if cache["token"] and time.monotonic() < float(cache["until"]):
        return str(cache["token"])
    basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    response = await http.request(
        "POST",
        _TOKEN,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        body=b"grant_type=client_credentials",
    )
    payload = parse_json(response)
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise ValueError("Jeton Spotify refusé.")
    cache["token"] = str(payload["access_token"])
    cache["until"] = time.monotonic() + max(30, int(payload.get("expires_in") or 3600) - 30)
    return str(cache["token"])


async def _search(http: HttpClient, token: str, query: str) -> list[dict[str, str]]:
    response = await http.request(
        "GET",
        with_query(_SEARCH, {"q": query, "type": "track", "limit": "5", "market": "FR"}),
        headers={"Authorization": f"Bearer {token}"},
    )
    payload = parse_json(response)
    items = ((payload.get("tracks") or {}) if isinstance(payload, dict) else {}).get("items")
    return [_track(item) for item in items or [] if isinstance(item, dict)][:5]


def _track(item: Mapping[str, Any]) -> dict[str, Any]:
    artists = item.get("artists") if isinstance(item.get("artists"), list) else []
    album = item.get("album") if isinstance(item.get("album"), dict) else {}
    names = ", ".join(
        str(artist.get("name") or "") for artist in artists if isinstance(artist, dict)
    )
    cover = _cover(album.get("images") if isinstance(album.get("images"), list) else [])
    seconds = int(item.get("duration_ms") or 0) // 1000
    return {
        "name": str(item.get("name") or ""),
        "artists": names,
        "album": str(album.get("name") or ""),
        "year": str(album.get("release_date") or "")[:4],
        "duration": f"{seconds // 60}:{seconds % 60:02d}" if seconds else "",
        "cover": cover,
        "explicit": bool(item.get("explicit")),
        "url": str((item.get("external_urls") or {}).get("spotify") or ""),
    }


def _cover(images: list[Any]) -> str:
    """La plus petite pochette d'au moins 300 px : assez nette pour une vignette."""
    sized = sorted(
        (item for item in images if isinstance(item, dict)), key=lambda item: item.get("width") or 0
    )
    for item in sized:
        if (item.get("width") or 0) >= 300:
            return str(item.get("url") or "")
    return str(sized[-1].get("url") or "") if sized else ""
