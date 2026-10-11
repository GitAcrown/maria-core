"""Recherche de morceau. Jeton client Spotify, mis en cache le temps de sa validité."""

import base64
import time
from collections.abc import Mapping
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.plugins import PluginHost

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
        description="Fiche Spotify d'un morceau. Inclus l'artiste si tu le connais.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        risk=Risk.EXTERNAL,
        run=run,
        requires=frozenset({"SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"}),
    )


def render_track(data: Mapping[str, Any]) -> str:
    lines = []
    for item in data.get("tracks") or []:
        if isinstance(item, dict):
            lines.append(f"- {item.get('artists')} — {item.get('name')} ({item.get('album')})")
    return "\n".join(lines)


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


def _track(item: Mapping[str, Any]) -> dict[str, str]:
    artists = item.get("artists") if isinstance(item.get("artists"), list) else []
    album = item.get("album") if isinstance(item.get("album"), dict) else {}
    names = ", ".join(
        str(artist.get("name") or "") for artist in artists if isinstance(artist, dict)
    )
    return {
        "name": str(item.get("name") or ""),
        "artists": names,
        "album": str(album.get("name") or ""),
        "url": str((item.get("external_urls") or {}).get("spotify") or ""),
    }
