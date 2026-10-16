"""Ce que MARIA annonce quand un outil tarde : une courte phrase, sans artifice."""

from collections.abc import Sequence

DELAY_S = 3.0
_DEFAULT = "Je m'en occupe…"
_LABELS = {
    "search_web": "Je cherche sur le web…",
    "read_web_page": "Je lis la page…",
    "read_youtube": "Je regarde la vidéo…",
    "get_weather": "Je consulte la météo…",
    "get_football": "Je consulte les scores…",
    "get_transport": "Je consulte les horaires…",
    "search_media": "Je cherche le film ou la série…",
    "search_game": "Je cherche le jeu…",
    "search_track": "Je cherche le morceau…",
    "search_images": "Je cherche des images…",
    "search_memory": "Je cherche dans mes souvenirs…",
    "summarize_channel": "Je résume le salon…",
    "run_python": "Je lance le calcul…",
    "calculate": "Je calcule…",
    "plot_function": "Je trace la courbe…",
    "render_chart": "Je prépare le graphique…",
    "render_diagram": "Je dessine le schéma…",
    "render_math": "Je prépare la formule…",
    "render_qr": "Je génère le QR code…",
}


def progress_label(names: Sequence[str]) -> str:
    """La phrase du premier outil connu du lot, sinon une formule neutre."""
    return next((_LABELS[name] for name in names if name in _LABELS), _DEFAULT)
