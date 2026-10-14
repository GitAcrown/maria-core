"""Films et séries via TMDB : la fiche du meilleur résultat, mise en page comme dans MARIA_R."""

from collections.abc import Mapping
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.plugins import PluginHost
from maria_core.ui.emojis import MOVIE, TV
from maria_core.ui.widgets import (
    Rendered,
    card,
    footer,
    grouped,
    joined,
    quote,
    separator,
    text,
    thumbnail,
)

_BASE = "https://api.themoviedb.org/3"
_POSTER = "https://image.tmdb.org/t/p/w500{}"
_TYPE_EMOJI = {"movie": MOVIE, "tv": TV}
_TYPE_LABEL = {"movie": "Film", "tv": "Série"}
_OVERVIEW = 380

NAME = "tmdb"


def setup(app: PluginHost) -> None:
    app.capabilities.register(media_capability(app.http, app.settings.tmdb_api_key))
    app.widgets.register("search_media", render_media)


def media_capability(http: HttpClient, api_key: str) -> Capability:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        query = str(args["query"]).strip()
        try:
            hits = await _search(http, api_key, query)
            if not hits:
                return Result(ok=False, data={}, error=f"Rien sur TMDB pour {query!r}.")
            best = await _details(http, api_key, hits[0])
        except (ValueError, HttpError) as exc:
            return Result(ok=False, data={}, error=str(exc))
        others = [f"{item['title']} ({item['date'][:4]})" for item in hits[1:4]]
        return Result(ok=True, data={**best, "others": others}, widget="search_media")

    return Capability(
        name="search_media",
        description=(
            "Fiche TMDB d'un film ou d'une série (note, synopsis, genres, durée ou saisons). "
            "Titre exact ou le plus précis, avec l'année si ambigu ; jamais un simple « et la "
            "suite ? » : complète avec le titre vu plus haut. Titre flou : search_web d'abord. "
            "Plusieurs œuvres : un appel par œuvre dans le même tour."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Titre, ex. Dune 2021"}},
            "required": ["query"],
        },
        risk=Risk.EXTERNAL,
        cache_s=21600,
        run=run,
        requires=frozenset({"TMDB_API_KEY"}),
    )


def render_media(data: Mapping[str, Any]) -> Rendered:
    kind = str(data.get("media_type") or "movie")
    year = str(data.get("date") or "")[:4]
    title = f"## {_TYPE_EMOJI.get(kind, MOVIE)} {data.get('title')}"
    if year:
        title += f"  ·  {year}"
    meta = joined(_TYPE_LABEL.get(kind, "Média"), *(data.get("genres") or [])[:3])
    overview = str(data.get("overview") or "").strip()
    if len(overview) > _OVERVIEW:
        overview = overview[:_OVERVIEW].rstrip(" ,;:") + "…"
    head = _rating(data) or "*Pas encore de note TMDB.*"
    built = card(
        text(f"{title}\n-# {meta}"),
        separator(wide=True),
        thumbnail(head, str(data.get("poster") or "")),
        text(quote(overview) if overview else "-# Aucune description disponible."),
        footer(_footer(data)),
    )
    note = f"{data.get('title')} ({year}) : {data.get('vote')}/10, {meta}. {overview[:200]}"
    return Rendered(cards=(built,), note=note)


def _rating(data: Mapping[str, Any]) -> str:
    vote = float(data.get("vote") or 0)
    count = int(data.get("votes") or 0)
    if not vote:
        return ""
    full = round(vote / 2)
    votes = f"  ·  {grouped(count)} votes" if count else ""
    return f"**TMDB** · {'★' * full}{'☆' * (5 - full)}  **{vote:.1f}/10**{votes}"


def _footer(data: Mapping[str, Any]) -> str:
    parts = [str(part) for part in (data.get("length"), data.get("language")) if part]
    if data.get("url"):
        parts.append(f"[TMDB](<{data['url']}>)")
    if data.get("others"):
        parts.append("aussi : " + ", ".join(data["others"]))
    return joined(*parts) or "TMDB"


async def _search(http: HttpClient, api_key: str, query: str) -> list[dict[str, Any]]:
    payload = await _json(
        http,
        f"{_BASE}/search/multi",
        {"api_key": api_key, "query": query, "language": "fr-FR", "include_adult": "false"},
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    hits = [_hit(item) for item in results or [] if isinstance(item, dict)]
    return [item for item in hits if item][:5]


async def _details(http: HttpClient, api_key: str, hit: dict[str, Any]) -> dict[str, Any]:
    kind = hit["media_type"]
    payload = await _json(
        http, f"{_BASE}/{kind}/{hit['id']}", {"api_key": api_key, "language": "fr-FR"}
    )
    genres = [
        str(item.get("name")) for item in payload.get("genres") or [] if isinstance(item, dict)
    ]
    language = str(payload.get("original_language") or "")
    return {
        **hit,
        "genres": genres[:3],
        "length": _length(payload),
        "language": language.upper() if language and language != "fr" else "",
        "votes": int(payload.get("vote_count") or hit["votes"] or 0),
        "overview": str(payload.get("overview") or hit["overview"])[:900],
        "url": f"https://www.themoviedb.org/{kind}/{hit['id']}",
    }


async def _json(http: HttpClient, url: str, params: dict[str, str]) -> dict[str, Any]:
    payload = parse_json(await http.request("GET", with_query(url, params)))
    if not isinstance(payload, dict):
        raise ValueError("Réponse TMDB inattendue.")
    return payload


def _hit(item: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(item.get("media_type") or "")
    if kind not in {"movie", "tv"}:
        return {}
    title = str(item.get("title") or item.get("name") or "")
    if not title or not item.get("id"):
        return {}
    poster = str(item.get("poster_path") or "")
    return {
        "id": int(item["id"]),
        "media_type": kind,
        "title": title,
        "date": str(item.get("release_date") or item.get("first_air_date") or ""),
        "vote": round(float(item.get("vote_average") or 0), 1),
        "votes": int(item.get("vote_count") or 0),
        "overview": str(item.get("overview") or "")[:400],
        "poster": _POSTER.format(poster) if poster else "",
    }


def _length(payload: Mapping[str, Any]) -> str:
    runtime = payload.get("runtime")
    if isinstance(runtime, int) and runtime > 0:
        hours, minutes = divmod(runtime, 60)
        return f"{hours}h{minutes:02d}" if hours else f"{minutes} min"
    seasons = payload.get("number_of_seasons")
    if isinstance(seasons, int) and seasons > 0:
        return f"{seasons} saison{'s' if seasons > 1 else ''}"
    return ""
