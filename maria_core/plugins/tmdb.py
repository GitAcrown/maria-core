"""Films et séries via TMDB."""

from collections.abc import Mapping
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.plugins import PluginHost

_SEARCH = "https://api.themoviedb.org/3/search/multi"


NAME = "tmdb"


def setup(app: PluginHost) -> None:
    app.capabilities.register(media_capability(app.http, app.settings.tmdb_api_key))
    app.widgets.register("search_media", render_media)


def media_capability(http: HttpClient, api_key: str) -> Capability:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        query = str(args["query"]).strip()
        try:
            hits = await _search(http, api_key, query)
        except (ValueError, HttpError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        if not hits:
            return Result(ok=False, data={}, error=f"Rien sur TMDB pour {query!r}.")
        return Result(ok=True, data={"results": hits}, widget="search_media")

    return Capability(
        name="search_media",
        description=(
            "Fiche TMDB d'un film ou d'une série : titre, date, note, synopsis. "
            "Passe le titre le plus précis possible, pas une question."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        risk=Risk.EXTERNAL,
        run=run,
        requires=frozenset({"TMDB_API_KEY"}),
    )


def render_media(data: Mapping[str, Any]) -> str:
    lines = []
    for item in data.get("results") or []:
        if isinstance(item, dict):
            lines.append(
                f"- {item.get('title')} ({item.get('date')}) "
                f"{item.get('vote')}/10 — {item.get('overview')}"
            )
    return "\n".join(lines)


async def _search(http: HttpClient, api_key: str, query: str) -> list[dict[str, str]]:
    response = await http.request(
        "GET",
        with_query(
            _SEARCH,
            {"api_key": api_key, "query": query, "language": "fr-FR", "include_adult": "false"},
        ),
    )
    payload = parse_json(response)
    results = payload.get("results") if isinstance(payload, dict) else None
    hits = [_hit(item) for item in results or [] if isinstance(item, dict)]
    return [item for item in hits if item][:5]


def _hit(item: Mapping[str, Any]) -> dict[str, str]:
    kind = str(item.get("media_type") or "")
    if kind not in {"movie", "tv"}:
        return {}
    title = str(item.get("title") or item.get("name") or "")
    if not title:
        return {}
    return {
        "title": title,
        "kind": "film" if kind == "movie" else "série",
        "date": str(item.get("release_date") or item.get("first_air_date") or ""),
        "vote": str(item.get("vote_average") or ""),
        "overview": str(item.get("overview") or "")[:400],
    }
