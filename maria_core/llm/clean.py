"""Nettoie une réponse du modèle avant de la poster : étiquettes, fuites, signature."""

import re

_REPLY_TAG = re.compile(r"^\s*\[à [^\]\n]{1,40}\]\s*")
_GAP_TAG = re.compile(r"\[…[^\]\n]{1,80}\]\s*")
_CONTEXT_TAG = re.compile(r"^\s*(?:\[contexte\]\s*)?\[\d{1,2}:\d{2}\]\s*[^:\n]{1,60}\(\d+\)\s*:\s*")
_SOURCE_MARK = re.compile(r"\s*[\[(]s\d+[)\]]", re.IGNORECASE)
_LEAKED = re.compile(
    r"\s*BEGIN:VEVENT.*?END:VEVENT\s*|\s*:?\bVEVENT\b\s*|\s*!?\[[^\]]*\]\(\s*widget\s*\)\s*"
    r"|\s*\[widget\]\s*",
    re.IGNORECASE | re.DOTALL,
)
_FOREIGN = (
    r"[Ѐ-ԯⷠ-ⷿꙀ-ꚟ֐-׿؀-ۿݐ-ݿ"
    r"ऀ-ॿ぀-ヿ㐀-鿿豈-﫿가-힯]+"
)
_TRAILING_FOREIGN = re.compile(
    r"(?P<body>.*[.!?…][\"'»”)\]*_`]*)(?P<trail>\s+" + _FOREIGN + r")\s*$", re.DOTALL
)
_LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿŒœÆæ]")
_PUNCT = re.compile(r"^[\s\"'«»*_`]+|[\s\"'«»*_`.,!?:;…\-—]+$")
_REACT = re.compile(r"\[\[REACT(?::[^\]]*)?\]\]", re.IGNORECASE)
_SKIP = re.compile(r"\[\[SKIP\]\]", re.IGNORECASE)
_SILENCE = re.compile(r"^\s*\[\[SILENCE\]\]\s*$", re.IGNORECASE)
_MEMORY = re.compile(r"\[\[MEM\]\](.*?)\[\[/MEM\]\]", re.DOTALL)


def clean_reply(text: str, bot_names: tuple[str, ...] = ()) -> str:
    """Retire ce que le modèle ne doit jamais poster. Vide si la réponse n'est que son nom."""
    cleaned = _REPLY_TAG.sub("", text or "")
    cleaned = _CONTEXT_TAG.sub("", cleaned)
    cleaned = _GAP_TAG.sub("", cleaned)
    cleaned = _MEMORY.sub(r"\1", cleaned)
    cleaned = _SOURCE_MARK.sub("", cleaned)
    cleaned = _LEAKED.sub(" ", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    cleaned = _strip_foreign_tail(cleaned)
    if is_name_only(cleaned, bot_names):
        return ""
    return cleaned


def silence_marks(text: str) -> tuple[str, bool, bool]:
    """(texte sans marque, veut réagir, veut se taire)."""
    wants_react = _REACT.search(text or "") is not None
    wants_skip = _SKIP.search(text or "") is not None
    stripped = _SKIP.sub("", _REACT.sub("", text or ""))
    return stripped.strip(), wants_react, wants_skip


def is_silence(text: str) -> bool:
    return _SILENCE.match(text or "") is not None


def is_name_only(text: str, names: tuple[str, ...]) -> bool:
    bare = _PUNCT.sub("", (text or "").strip())
    if not bare or len(bare) > 24:
        return False
    folded = bare.casefold()
    return any(folded == name.casefold() for name in (*names, "maria"))


def _strip_foreign_tail(text: str) -> str:
    """Un court bout d'écriture non latine collé après une phrase latine est une fuite."""
    match = _TRAILING_FOREIGN.match(text)
    if match is None:
        return text
    body = match.group("body")
    foreign = sum(len(part) for part in re.findall(_FOREIGN, match.group("trail")))
    if not 2 <= foreign <= 24 or len(_LATIN.findall(body)) < 8:
        return text
    if len("".join(re.findall(_FOREIGN, body))) >= 3:
        return text
    return body.rstrip()
