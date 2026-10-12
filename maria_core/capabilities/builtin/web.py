"""Recherche, actualités, lecture de page et images. Brave pour chercher, la page pour lire."""

from collections.abc import Callable, Mapping
from typing import Any

from maria_core.capabilities.base import Capability, Context, Result, Risk, Source
from maria_core.capabilities.http import HttpClient, HttpError, parse_json, with_query
from maria_core.capabilities.net import assert_public_host
from maria_core.capabilities.page import Resolver, fetch_text
from maria_core.ui.render import split_message
from maria_core.ui.widgets import Rendered, card, gallery

_SEARCH = "https://api.search.brave.com/res/v1/web/search"
_NEWS = "https://api.search.brave.com/res/v1/news/search"
_IMAGES = "https://api.search.brave.com/res/v1/images/search"
_PAGE_CHARS = 4000
_MAX_IMAGES = 4


def web_capabilities(
    http: HttpClient,
    api_key: str,
    *,
    resolve: Resolver = assert_public_host,
) -> tuple[Capability, ...]:
    return (
        _tool("search_web", _SEARCH_TEXT, _search_schema(), _search(http, api_key)),
        _tool("read_web_page", _READ_TEXT, _read_schema(), _read(http, resolve)),
        _tool("search_images", _IMAGE_TEXT, _image_schema(), _images(http, api_key)),
    )


def render_images(data: Mapping[str, Any]) -> Rendered:
    urls = [
        str(item.get("url") or "") for item in data.get("images") or [] if isinstance(item, dict)
    ]
    return Rendered(
        cards=(card(gallery(urls)),), note=f"Images affichées : {data.get('query', '')}"
    )


async def brave_search(
    http: HttpClient, api_key: str, query: str, *, lang: str = "fr", news: bool = False
) -> list[dict[str, str]] | str:
    """Résultats web ou d'actualité ; une chaîne d'erreur si Brave ne répond pas."""
    url = _NEWS if news else _SEARCH
    payload = await _brave(http, url, api_key, {"q": query, "count": "5", "search_lang": lang})
    if isinstance(payload, str):
        return payload
    return _news_hits(payload) if news else _web_hits(payload)


def _tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    run: Callable[[Context, Mapping[str, Any]], Any],
) -> Capability:
    return Capability(
        name=name,
        description=description,
        parameters=parameters,
        risk=Risk.EXTERNAL,
        run=run,
        requires=frozenset({"BRAVE_API_KEY"}) if name != "read_web_page" else frozenset(),
    )


def _search(http: HttpClient, api_key: str) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        news = args.get("news") is True
        hits = await brave_search(http, api_key, str(args["query"]), lang=_lang(args), news=news)
        if isinstance(hits, str):
            return Result(ok=False, data={}, error=hits)
        if not hits:
            return Result(ok=True, data={"results": [], "note": "Aucun résultat : reformule."})
        sources = tuple(Source(title=item["title"], url=item["url"]) for item in hits)
        return Result(ok=True, data={"results": hits}, sources=sources)

    return run


def _images(http: HttpClient, api_key: str) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        count = max(1, min(_MAX_IMAGES, int(args.get("count") or 1)))
        query = str(args["query"])
        payload = await _brave(
            http,
            _IMAGES,
            api_key,
            {"q": query, "count": str(count + 2), "search_lang": _lang(args)},
        )
        if isinstance(payload, str):
            return Result(ok=False, data={}, error=payload)
        images = _image_hits(payload)[:count]
        if not images:
            return Result(ok=False, data={}, error="Aucune image trouvée.")
        return Result(ok=True, data={"images": images, "query": query}, widget="search_images")

    return run


def _read(http: HttpClient, resolve: Resolver) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        try:
            text, url = await fetch_text(http, str(args["url"]), resolve=resolve)
        except (ValueError, UnicodeError) as exc:
            return Result(ok=False, data={}, error=str(exc) or "Lecture impossible.")
        pages = split_message(text, limit=_PAGE_CHARS)
        index = _chunk(args.get("chunk"), len(pages))
        return Result(
            ok=True,
            data={
                "url": url,
                "content": pages[index],
                "chunk": index,
                "total_chunks": len(pages),
                "next_chunk": index + 1 if index + 1 < len(pages) else None,
            },
        )

    return run


async def _brave(http: HttpClient, url: str, api_key: str, params: dict[str, str]) -> Any:
    try:
        response = await http.request(
            "GET",
            with_query(url, params),
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        )
        return parse_json(response)
    except (ValueError, HttpError) as exc:
        return str(exc)


def _web_hits(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    web = payload.get("web") if isinstance(payload, Mapping) else None
    results = web.get("results") if isinstance(web, Mapping) else None
    return _hits(results)


def _news_hits(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    results = payload.get("results") if isinstance(payload, Mapping) else None
    hits = _hits(results)
    for hit, item in zip(hits, results or [], strict=False):
        if isinstance(item, Mapping) and item.get("age"):
            hit["age"] = str(item["age"])
    return hits


def _hits(results: object) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, Mapping) or not item.get("url"):
            continue
        hits.append(
            {
                "title": str(item.get("title") or item["url"]),
                "url": str(item["url"]),
                "snippet": str(item.get("description") or "")[:400],
            }
        )
    return hits[:5]


def _image_hits(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    hits = []
    for item in payload.get("results") or [] if isinstance(payload, Mapping) else []:
        if not isinstance(item, Mapping):
            continue
        properties = item.get("properties") if isinstance(item.get("properties"), Mapping) else {}
        url = str(properties.get("url") or item.get("url") or "")
        if url.startswith("https://"):
            hits.append({"title": str(item.get("title") or ""), "url": url})
    return hits


def _lang(args: Mapping[str, Any]) -> str:
    lang = str(args.get("lang") or "fr").strip().lower()
    return lang or "fr"


def _chunk(raw: object, total: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    return max(0, min(raw, total - 1))


def _search_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Requête précise (noms, date, lieu)"},
            "lang": {"type": "string", "description": "Code langue, défaut fr"},
            "news": {"type": "boolean", "description": "true pour l'actualité récente"},
        },
        "required": ["query"],
    }


def _read_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL https complète"},
            "chunk": {"type": "integer", "description": "Morceau à lire, 0 au début"},
        },
        "required": ["url"],
    }


def _image_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Ce qu'il faut montrer"},
            "count": {"type": "integer", "minimum": 1, "maximum": _MAX_IMAGES},
            "lang": {"type": "string"},
        },
        "required": ["query"],
    }


_SEARCH_TEXT = (
    "Recherche web (faits, dates, chiffres) ; news=true pour l'actualité. Une requête par "
    "question, pas de seconde « pour confirmer ». Si les extraits suffisent, réponds ; sinon "
    "read_web_page. Les sources sont affichées sous ta réponse : n'écris ni [s1] ni liste de liens."
)
_READ_TEXT = (
    "Lit une URL déjà connue (recherche ou lien du message). "
    "Si next_chunk est présent, rappelle cet outil avec chunk=next_chunk. "
    "Pas pour YouTube (read_youtube)."
)
_IMAGE_TEXT = (
    "Cherche des images et les affiche en galerie. count entre 1 et 4, défaut 1. "
    "Plusieurs sujets : un appel par sujet dans le même tour, une seule galerie."
)
