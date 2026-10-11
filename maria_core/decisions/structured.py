"""Backend JEV. Sans clé, ou si l'appel échoue, le moteur prend le repli."""

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul

from maria_core.decisions.types import Question, StructuredAnswer

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 4.0
_MODEL = "jev-latest"


class JevBackend:
    """Client ouvert au premier appel. Une clé vide n'envoie rien."""

    def __init__(self, api_key: str, *, model: str = _MODEL) -> None:
        self._api_key = api_key.strip()
        self._model = model
        self._client: Any = None

    async def ask(
        self,
        state: Mapping[str, Any],
        question: Question,
    ) -> StructuredAnswer | None:
        if not self._api_key:
            return None
        try:
            result = await asyncio.wait_for(
                self._client_or_create().system_one(dict(state), _payload(question)),
                timeout=_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning("JEV %s : délai dépassé", question.field)
            return None
        except Exception:
            logger.warning("JEV %s échoué", question.field, exc_info=True)
            return None
        return read_answer(result, question)

    async def close(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            await client.aclose()
        except Exception:
            logger.debug("Fermeture JEV ignorée", exc_info=True)

    def _client_or_create(self) -> Any:
        if self._client is None:
            self._client = AsyncTypeSafeClient(api_key=self._api_key, model=self._model)
        return self._client


def _payload(question: Question) -> dict[str, Any]:
    if question.kind == "noul":
        item: Any = Noul(instructions=question.instructions, criteria=dict(question.criteria))
    else:
        item = Choice(instructions=question.instructions, criteria=dict(question.criteria))
    return {question.field: item}


def read_answer(result: Any, question: Question) -> StructuredAnswer | None:
    if result is None:
        return None
    if question.kind == "noul":
        return _read_noul(result, question.field)
    return _read_choice(result, question.field)


def _read_choice(result: Any, field: str) -> StructuredAnswer | None:
    try:
        answer = result.choices[field]
        confidence = float(getattr(answer, "confidence", 0.0) or 0.0)
        return StructuredAnswer(str(answer.choice), confidence)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _read_noul(result: Any, field: str) -> StructuredAnswer | None:
    """Le noul est la probabilité du oui. La confiance porte sur la réponse choisie."""
    try:
        noul = float(result.nouls[field].noul)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if noul >= 0.5:
        return StructuredAnswer(True, noul)
    return StructuredAnswer(False, 1.0 - noul)
