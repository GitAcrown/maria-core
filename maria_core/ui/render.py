"""Découpe un texte pour la limite de message Discord."""

DISCORD_LIMIT = 2000


def split_message(text: str, *, limit: int = DISCORD_LIMIT) -> tuple[str, ...]:
    """Coupe de préférence sur un saut de ligne, sinon sur un espace.

    Un bloc ``` coupé est refermé à la fin du morceau et rouvert au suivant.
    """
    remaining = (text or "").strip()
    if not remaining:
        return ()
    if limit < 1:
        raise ValueError("La limite doit être positive.")
    chunks: list[str] = []
    prefix = ""
    while remaining:
        piece, remaining, prefix = _take(remaining, limit, prefix)
        if piece:
            chunks.append(piece)
    return tuple(chunks)


def _take(remaining: str, limit: int, prefix: str) -> tuple[str, str, str]:
    budget = limit - len(prefix)
    if budget < 1:
        budget = limit
        prefix = ""
    if len(remaining) <= budget:
        return prefix + remaining, "", ""
    cut = _cut_at(remaining, budget)
    piece = remaining[:cut].rstrip()
    rest = remaining[cut:].lstrip()
    if not piece:
        piece, rest = remaining[:budget], remaining[budget:].lstrip()
    body = prefix + piece
    if body.count("```") % 2 == 0:
        return body, rest, ""
    closed, rest = _close_fence(body, rest, limit)
    return closed, rest, "```\n"


def _close_fence(body: str, rest: str, limit: int) -> tuple[str, str]:
    closer = "\n```"
    if len(body) + len(closer) <= limit:
        return body + closer, rest
    if limit <= len(closer):
        return body, rest
    kept = body[: limit - len(closer)].rstrip()
    return kept + closer, f"{body[len(kept) :]}{rest}"


def _cut_at(text: str, limit: int) -> int:
    newline = text.rfind("\n", 0, limit)
    if newline >= limit // 2:
        return newline
    space = text.rfind(" ", 0, limit)
    if space >= limit // 2:
        return space
    return limit
