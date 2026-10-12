"""Ce que le modèle sait du tour : salon, focus, citation, fichiers. Rien n'est persisté ici."""

import re
from collections.abc import Callable
from datetime import UTC, datetime

from maria_core.conversation.model import Inbound, Route
from maria_core.llm.history import HistoryEntry

type ContextSource = Callable[[Inbound], str]

FOCUS_CHARS = 240
FILE_CHARS = 6000

SILENCE_GUIDE = (
    "SILENCE : ce message n'attend pas forcément une réponse écrite. Blague, constat, "
    "« ok », truc cool : réponds seulement `[[REACT]]` (un emoji sera posé). "
    "`[[SKIP]]` seul si même une réaction n'a pas de sens. Question ou demande, "
    "même implicite : vraie réponse."
)
_REACT_REQUEST = re.compile(
    r"\br[ée]agi[st]?\b|\br[ée]agir\b|\br[ée]agissez\b"
    r"|\b(?:mets?|ajoute|fais|rajoute)\s+(?:moi\s+)?(?:une?\s+)?(?:petite?\s+)?r[ée]action\b"
    r"|\breact\b",
    re.IGNORECASE,
)
_STRONG_REQUEST = re.compile(
    r"\br[ée]agis\b|\br[ée]agir\b|\br[ée]agissez\b"
    r"|\b(?:mets?|ajoute[rz]?|fais|mettre|rajoute)\s+(?:moi\s+)?(?:une?\s+|des\s+)?"
    r"(?:petite?\s+)?r[ée]action\b",
    re.IGNORECASE,
)
_MINE = re.compile(r"\b(?:mon|ma|mes)\b", re.IGNORECASE)
_URL_ONLY = re.compile(r"https?://\S+", re.IGNORECASE)


def turn_header(message: Inbound, *, model: str) -> str:
    """Repères propres au tour, ajoutés au prompt système."""
    name = message.bot_names[-1] if message.bot_names else "MARIA"
    lines = [f"Ton nom ici : {name}. Modèle : {model or 'inconnu'} (OpenAI) ; détails : about_me."]
    if message.channel_label:
        lines.append(f"SALON ACTUEL : {message.channel_label}")
    return "\n".join(lines)


def focus_note(message: Inbound, files: str = "") -> dict[str, str]:
    """Rappel éphémère : quel message traiter. Jamais gardé dans l'historique."""
    who = f"{message.author_name} ({message.author_id})"
    content = strip_address(message.text, message.bot_names)[:FOCUS_CHARS]
    if content:
        hint = (
            f"[FOCUS] Texte écrit par {who} : « {content} ». C'est SON message : réponds à ça, "
            "pas à une autre question du [contexte]. Lis l'intention, pas l'orthographe."
        )
    else:
        hint = f"[FOCUS] {who} t'envoie un média ou un message sans texte."
    if message.quote is not None:
        hint += " " + _quote_hint(message, bool(content))
    if files:
        hint += f"\n{files}"
    return {"role": "user", "content": hint}


def can_stay_silent(message: Inbound, route: Route) -> bool:
    """Silence ou emoji permis : pas de ping, pas de reply à MARIA, pas de question."""
    if message.mentioned or message.reply_to_bot or message.mention_everyone:
        return False
    if message.is_dm or message.transcribed or "?" in message.text:
        return False
    return route.reason in {"name_edge", "name_middle", "name_model", "followup"}


def is_reaction_request(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if len(cleaned) <= 80:
        return bool(_REACT_REQUEST.search(cleaned) or _STRONG_REQUEST.search(cleaned))
    return len(cleaned) <= 400 and _STRONG_REQUEST.search(cleaned) is not None


def reaction_target(message: Inbound) -> int:
    """« réagis à son message » vise le message cité ; « à mon message », le sien."""
    quote = message.quote
    if quote is not None and not quote.from_bot and _MINE.search(message.text) is None:
        return quote.message_id
    return message.message_id


def is_media_only(message: Inbound) -> bool:
    rest = _URL_ONLY.sub("", message.text).strip()
    return not rest and (message.has_media or bool(message.text.strip()))


def user_entry(message: Inbound, *, addressed: bool, files: str = "") -> HistoryEntry:
    body = _body(message)
    if files:
        body = f"{body}\n{files}".strip()
    images = tuple(image.url for image in message.images) if addressed else ()
    if addressed and message.quote is not None and not message.quote.from_bot_self:
        images += tuple(image.url for image in message.quote.images)
    return HistoryEntry(
        role="user",
        content=body or ("[média]" if message.has_media else "(message vide)"),
        created_at=message.created_at if message.created_at.tzinfo else datetime.now(UTC),
        message_id=message.message_id,
        name=message.author_name,
        images=images[:4],
        author_id=message.author_id,
        context_only=not addressed,
    )


def strip_address(text: str, names: tuple[str, ...]) -> str:
    """« Maria, … » : le prénom en tête n'est pas le contenu. Seul, il reste."""
    out = re.sub(r"^<@!?\d+>\s*", "", (text or "").strip())
    for name in sorted({*names, "Maria"}, key=len, reverse=True):
        stripped = re.sub(
            rf"^{re.escape(name)}\b[\s,.:;!?…\-—]*", "", out, count=1, flags=re.IGNORECASE
        )
        if stripped != out:
            out = stripped
            break
    return out.strip() or (text or "").strip()


def _body(message: Inbound) -> str:
    parts: list[str] = []
    if message.quote is not None:
        parts.append(_quote_line(message))
    text = message.text.strip()
    if message.transcribed:
        text = f"(vocal) {text}"
    if text:
        parts.append(text)
    parts.extend(message.extras)
    return "\n".join(parts)


def _quote_line(message: Inbound) -> str:
    quote = message.quote
    if quote is None:
        return ""
    preview = quote.text[:200]
    if quote.from_bot_self:
        return f'[Cité (reply) — c\'est TOI qui as écrit : "{preview}"]'
    who = f"{quote.author_name} ({quote.author_id})"
    return f'[Cité (reply, pas le texte de ce membre) — répond à {who} : "{preview}"]'


def _quote_hint(message: Inbound, has_text: bool) -> str:
    quote = message.quote
    if quote is None:
        return ""
    if quote.from_bot_self:
        hint = (
            "Iel répond à TON message : tu l'as écrit, parles-en à la 1re personne. "
            "Son message précise ou corrige ta réponse : reste sur ce sujet."
        )
    else:
        hint = (
            f"Iel cite un message de {quote.author_name} : c'est une CITATION, pas son texte, "
            "ne la lui attribue pas."
        )
    if not has_text:
        hint += " Son message est vide : la demande porte sur le message cité."
    return hint
