"""Fiche de MARIA, chargée seulement quand on la lui demande."""

import platform
from collections.abc import Mapping
from typing import Any

from maria_core.capabilities.base import Capability, CapabilityRegistry, Context, Result, Risk
from maria_core.llm.client import MODEL_FALLBACK, MODEL_MAIN, MODEL_TRANSCRIBE

_TOPICS = ("identity", "tech", "tools", "limits", "all")


def about_capability(registry: CapabilityRegistry) -> Capability:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        topic = str(args.get("topic") or "all")
        sections = _sections(registry)
        if topic == "all":
            return Result(ok=True, data={"topic": "all", "sections": sections})
        return Result(ok=True, data={"topic": topic, "section": sections.get(topic, "")})

    return Capability(
        name="about_me",
        description=(
            "Fiche interne : qui est MARIA, sa stack, ses outils, ses limites. "
            "Pour « t'es qui », comment tu marches, quel modèle. Pas pour le tchat banal."
        ),
        parameters={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": list(_TOPICS),
                    "description": "identity, tech, tools, limits, ou all",
                },
            },
            "required": ["topic"],
        },
        risk=Risk.READ,
        run=run,
    )


def _sections(registry: CapabilityRegistry) -> dict[str, str]:
    tools = ", ".join(registry.names()) or "aucun"
    return {
        "identity": (
            "MARIA est un bot Discord. Créateur : acrone. "
            "Elle parle comme quelqu'un du salon, elle n'invente pas de faits, "
            "et elle le dit quand un outil n'a rien donné."
        ),
        "tech": (
            f"Modèle {MODEL_MAIN}, repli {MODEL_FALLBACK}, transcription {MODEL_TRANSCRIBE}. "
            f"Python {platform.python_version()} sur {platform.system()}. "
            "Mémoire de salon en process, base SQLite, décisions règles puis JEV."
        ),
        "tools": tools,
        "limits": (
            "Elle ne vote pas aux sondages et ne voit pas les votes en cours. "
            "run_python est réservé au propriétaire, et à un serveur qui l'a activé. "
            "Sans la clé d'une capacité, cette capacité n'existe pas pour elle."
        ),
    }
