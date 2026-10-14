"""Rédige le message d'un objectif au moment voulu, avec les outils. Ni tchat ni historique."""

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime

from maria_core.capabilities import CapabilityRegistry, Context, Result
from maria_core.capabilities.runner import SlotSource, available, invoke
from maria_core.config import Settings
from maria_core.conversation.compose import compose
from maria_core.db import Database
from maria_core.llm.clean import is_silence
from maria_core.llm.loop import LoopResult, complete_turn
from maria_core.llm.schema import openai_tool
from maria_core.llm.types import ChatClient, ToolCall
from maria_core.objectives.model import Objective
from maria_core.objectives.pipeline import Written
from maria_core.objectives.schedule import PARIS
from maria_core.ui.widgets import WidgetRegistry

logger = logging.getLogger(__name__)

type Profile = Callable[[int, int | None], str]

DENIED = frozenset(
    {
        "objective_create",
        "objective_update",
        "objective_list",
        "objective_show",
        "remember_fact",
        "forget_fact",
        "search_memory",
        "get_server_users",
        "get_member_info",
        "get_channel_info",
        "about_me",
        "summarize_channel",
        "create_poll",
    }
)
_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_META = re.compile(
    r"\([^)\n]{0,500}\b(?:ping|mention|reply|discord|instruction)\b[^)\n]{0,500}\)",
    re.IGNORECASE,
)
_SYSTEM = """Tu es MARIA. L'heure d'un objectif est arrivée : tu l'EXÉCUTES maintenant.

CONSIGNE (rien d'autre) :
{instruction}

- Une phrase, deux max, sauf si la consigne demande un récap. Uniquement ce qui est demandé.
- Pas de @, pas de question, pas de suite, pas de « je te rappellerai ».
- Faits actuels : appelle l'outil DANS CE TOUR, n'invente rien (météo, transports, scores, web…).
  Ville ou détail absent : regarde le PROFIL du destinataire.
- Condition dans la consigne : vérifie-la d'abord. Fausse ou preuve insuffisante → ta réponse est
  exactement [[SILENCE]].
- Tutoiement, sans emoji, sans commencer par ton nom.
{runs}{profile}
CONTEXTE :
{evidence}

DATE/HEURE : {now} (Paris)"""


class ReportWriter:
    def __init__(
        self,
        *,
        client: ChatClient,
        capabilities: CapabilityRegistry,
        settings: Settings,
        database: Database,
        widgets: WidgetRegistry,
        profile: Profile | None = None,
        slots: SlotSource | None = None,
    ) -> None:
        self._client = client
        self._capabilities = capabilities
        self._settings = settings
        self._database = database
        self._widgets = widgets
        self._profile = profile
        self._slots = slots

    async def write(
        self,
        objective: Objective,
        instruction: str,
        evidence: str,
        runs: tuple[tuple[str, str], ...],
    ) -> Written | None:
        profile = ""
        if self._profile is not None:
            profile = await asyncio.to_thread(self._profile, objective.owner_id, objective.guild_id)
        system = _SYSTEM.format(
            instruction=instruction,
            runs=_runs(runs),
            profile=f"\n{profile}\n" if profile else "",
            evidence=evidence[:2500],
            now=_now_text(),
        )
        outcome = await self._loop(objective, system, instruction)
        await asyncio.to_thread(self._log, outcome)
        composed = compose(outcome, self._widgets, ())
        text = clean_task_text(composed.text)
        if not outcome.ok or is_silence(outcome.text) or (not text and not composed.cards):
            return None
        return Written(text, composed.cards)

    async def _loop(self, objective: Objective, system: str, instruction: str) -> LoopResult:
        context = Context(
            user_id=objective.owner_id,
            guild_id=objective.guild_id,
            channel_id=objective.channel_ids[0] if objective.channel_ids else objective.owner_id,
            message_id=None,
            is_owner=False,
            is_moderator=False,
            text=instruction,
        )
        tools = [
            openai_tool(item)
            for item in available(self._capabilities, self._settings)
            if item.name not in DENIED
        ]

        async def execute(call: ToolCall) -> Result:
            if call.name in DENIED:
                return Result(ok=False, data={}, error="Outil indisponible pendant un objectif.")
            return await invoke(
                self._capabilities,
                self._settings,
                context,
                call,
                database=self._database,
                slots=self._slots,
            )

        prompt = [
            {"role": "user", "content": f"[OBJECTIF #{objective.id}] Exécute : {instruction}"}
        ]
        return await complete_turn(
            self._client, prompt, system=system, tools=tools, execute=execute
        )

    def _log(self, outcome: LoopResult) -> None:
        self._database.execute(
            """
            INSERT INTO llm_calls (
                at, purpose, model, input_tokens, output_tokens, duration_ms, ok
            ) VALUES (?, 'objective', ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(UTC).isoformat(),
                outcome.model,
                outcome.input_tokens,
                outcome.output_tokens,
                outcome.duration_ms,
                1 if outcome.ok else 0,
            ),
        )


def clean_task_text(text: str) -> str:
    """Retire les apartés du modèle sur la mécanique (ping, consigne) et les lignes doublées."""
    raw = _META.sub("", text or "")
    raw = re.sub(r"<@!?\d+>\s*", "", raw)
    kept: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped and stripped.casefold() in seen:
            continue
        seen.add(stripped.casefold())
        kept.append(line.rstrip())
    return "\n".join(kept).strip()


def _runs(runs: tuple[tuple[str, str], ...]) -> str:
    if not runs:
        return ""
    lines = [f"- {stamp[:10]} : {summary[:200]}" for stamp, summary in runs]
    return (
        "\nDÉJÀ ENVOYÉ (du plus ancien au plus récent) : si la consigne varie (mot, quiz, "
        "anecdote), ne reprends pas un item déjà listé. Un état (météo, statut) se redonne.\n"
        + "\n".join(lines)
        + "\n"
    )


def _now_text() -> str:
    local = datetime.now(UTC).astimezone(PARIS)
    return f"{_DAYS[local.weekday()]} {local:%Y-%m-%d %H:%M}"
