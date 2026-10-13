"""Toutes les icônes des vues de MARIA, au même endroit.

Emojis custom (repris de MARIA_R, repli Unicode si le bot n'y a pas accès), puis les icônes
Unicode des types de programme.
"""

FOOTBALL = "<:football:1517996110453670062>"
FOOTBALL_PLAYER = "<:footballplayer:1517996109581258832>"
DIRECT = "<:direct:1517996113360064682>"
MOVIE = "<:movie:1517996108670832660>"
TV = "<:tv:1517996107748216893>"
GAMES = "<:games:1517996105529561270>"
MUSIC = "<:music:1533911299908698122>"
YOUTUBE = "<:youtube1:1538993229331042345>"
TRAIN = "<:train:1538180467856113695>"
TRANSCRIPT = "<:transcript:1517996112001372303>"
TRANSCRIPT_SUB = "<:m_small_trasncript:1555888662049456209>"

FALLBACKS = {
    FOOTBALL: "⚽",
    FOOTBALL_PLAYER: "⚽",
    DIRECT: "🔴",
    MOVIE: "🎬",
    TV: "📺",
    GAMES: "🎮",
    MUSIC: "🎵",
    YOUTUBE: "▶️",
    TRAIN: "🚆",
    TRANSCRIPT: "📝",
    TRANSCRIPT_SUB: "📝",
}


def emoji_id(tag: str) -> int:
    return int(tag.rstrip(">").rsplit(":", 1)[1])


def downgrade(text: str, usable: frozenset[int] | None) -> str:
    """Remplace les emojis custom inaccessibles au bot par leur équivalent Unicode."""
    if usable is None or "<:" not in text:
        return text
    for tag, plain in FALLBACKS.items():
        if tag in text and emoji_id(tag) not in usable:
            text = text.replace(tag, plain)
    return text


KIND_ICONS = {
    "Rappel": "⏰",
    "Rappel récurrent": "🔁",
    "Écoute": "👂",
    "Surveillance": "🔎",
    "Veille de prix": "🏷️",
    "Alerte vocale": "🔊",
    "Alerte d'arrivée": "👋",
    "Tâche programmée": "🗓️",
    "Tâche": "🗓️",
}
