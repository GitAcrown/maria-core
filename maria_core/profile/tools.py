"""Outil du modèle : régler un champ du profil quand la personne le demande clairement."""

import asyncio
from collections.abc import Mapping
from typing import Any

from maria_core.capabilities import Capability, Context, Result, Risk
from maria_core.profile.service import Profiles
from maria_core.profile.slots import SLOTS, STYLE

_TEXT = (
    "Règle un champ du profil de la personne, quand elle le demande ou le dit sans ambiguïté : "
    "« j'habite à Lyon » (city), « mon équipe c'est l'OM » (team), « mon métro c'est République » "
    "(stop), « mon anniversaire c'est le 22 juillet » (birthday, jour et mois), "
    "« réponds-moi plus court » (length), « tutoie-moi, détends-toi » (tone), "
    "« mets des emojis » (emoji). value vide : efface le champ. Elle le voit dans /moi."
)


def profile_capability(profiles: Profiles) -> Capability:
    async def run(context: Context, args: Mapping[str, Any]) -> Result:
        key = str(args["slot"])
        value = str(args.get("value") or "").strip()
        try:
            if value:
                kept = await asyncio.to_thread(
                    profiles.store.set, context.user_id, key, value, profiles.now()
                )
            else:
                await asyncio.to_thread(profiles.store.clear, context.user_id, key)
                kept = ""
        except ValueError as exc:
            return Result(ok=False, data={}, error=str(exc))
        return Result(ok=True, data={"slot": key, "value": kept, "cleared": not kept})

    return Capability(
        name="profile_set",
        description=_TEXT,
        parameters={
            "type": "object",
            "properties": {
                "slot": {"type": "string", "enum": [slot.key for slot in SLOTS]},
                "value": {
                    "type": "string",
                    "description": "Ville, équipe, arrêt ou anniversaire (22 juillet) en clair ; "
                    "pour le style : "
                    + ", ".join(f"{s.key}={'/'.join(v for v, _ in s.choices)}" for s in STYLE),
                },
            },
            "required": ["slot"],
        },
        risk=Risk.WRITE,
        run=run,
    )
