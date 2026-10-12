"""Lecture d'une page et recherche web pour fetch_then. Les tests injectent leurs fonctions."""

from maria_core.capabilities.builtin.web import brave_search
from maria_core.capabilities.http import HttpClient
from maria_core.capabilities.page import fetch_text
from maria_core.objectives.pipeline import Fetcher, Searcher


def http_fetcher(http: HttpClient) -> Fetcher:
    async def fetch(url: str) -> str:
        text, _final = await fetch_text(http, url)
        return text

    return fetch


def brave_searcher(http: HttpClient, api_key: str) -> Searcher:
    """(extraits, première URL). Vide sans clé ou sans résultat."""

    async def search(query: str) -> tuple[str, str]:
        if not api_key or not query.strip():
            return "", ""
        hits = await brave_search(http, api_key, query, lang="fr", news=False)
        if isinstance(hits, str) or not hits:
            return "", ""
        lines = [f"{item['title']} — {item['snippet']}".strip(" —") for item in hits[:4]]
        return f"Recherche « {query} » :\n" + "\n".join(lines), hits[0]["url"]

    return search
