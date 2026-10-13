"""Résumé de la mémoire pour /moi et /global, repris de MARIA_R. Mis en cache par contenu."""

import logging
from collections import OrderedDict

from maria_core.llm.types import ChatClient
from maria_core.memory.model import Memory

logger = logging.getLogger(__name__)

_CACHE_MAX = 256
_PERSONAL = (
    "Résume ce que MARIA sait d'un membre, à partir de ses souvenirs personnels. "
    "2 à 5 phrases courtes et naturelles, à la 2e personne (« tu… »). Pas de liste, "
    "pas d'emoji, pas d'intro. Peu d'éléments ou du flou : dis que tu ne sais presque rien. "
    "N'invente rien."
)
_COLLECTIVE = (
    "Résume la mémoire collective d'un serveur Discord (gags, habitudes, événements). "
    "2 à 5 phrases courtes et naturelles, à la 3e personne (« le serveur… », « on… »). "
    "Pas de liste, pas d'emoji, pas d'intro. Peu d'éléments : dis que peu est retenu. "
    "N'invente rien."
)
EMPTY_PERSONAL = "Je n'ai encore rien de solide en mémoire sur toi."
EMPTY_COLLECTIVE = "Peu de choses retenues sur le serveur pour l'instant."


class MemorySummaries:
    def __init__(self, client: ChatClient) -> None:
        self._client = client
        self._cache: OrderedDict[tuple[object, ...], str] = OrderedDict()

    async def summarize(
        self, memories: tuple[Memory, ...], *, collective: bool, name: str = ""
    ) -> str:
        if not memories:
            return EMPTY_COLLECTIVE if collective else EMPTY_PERSONAL
        key = (collective, name, tuple(sorted((item.id, item.content) for item in memories)))
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        text = await self._ask(memories, collective=collective, name=name)
        if not text:
            return "\n".join(f"\u203a {item.content}" for item in memories[:8])
        self._cache[key] = text
        while len(self._cache) > _CACHE_MAX:
            self._cache.popitem(last=False)
        return text

    async def _ask(self, memories: tuple[Memory, ...], *, collective: bool, name: str) -> str:
        header = f"Membre : {name}\n" if name and not collective else ""
        lines = "\n".join(f"- {item.content}" for item in memories[:80])
        messages = [
            {"role": "system", "content": _COLLECTIVE if collective else _PERSONAL},
            {"role": "user", "content": f"{header}Souvenirs :\n{lines}"},
        ]
        try:
            completion = await self._client.complete(messages)
        except Exception:
            logger.warning("Résumé de mémoire en échec", exc_info=True)
            return ""
        return completion.text.strip()
