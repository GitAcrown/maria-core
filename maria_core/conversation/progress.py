"""Ce que MARIA annonce quand sa réponse tarde : une courte phrase, jamais deux fois la même."""

import random
from collections.abc import Sequence

DELAY_S = 2.0
_DEFAULT = ("Je m'en occupe…", "Je regarde ça…", "Je m'y mets…")
_LABELS: dict[str, tuple[str, ...]] = {
    "search_web": (
        "Je cherche sur le web…",
        "Je lance une recherche…",
        "Je regarde ce qu'on trouve en ligne…",
    ),
    "read_web_page": (
        "Je lis la page…",
        "J'ouvre la page…",
        "Je parcours le contenu de la page…",
    ),
    "read_youtube": (
        "Je regarde la vidéo…",
        "Je récupère la vidéo…",
        "Je lis le contenu de la vidéo…",
    ),
    "get_weather": (
        "Je consulte la météo…",
        "Je vérifie les prévisions…",
        "Je regarde le temps qu'il fait…",
    ),
    "get_football": (
        "Je consulte les scores…",
        "Je vérifie les résultats…",
        "Je regarde les matchs…",
    ),
    "get_transport": (
        "Je consulte les horaires…",
        "Je vérifie les prochains passages…",
        "Je regarde les trajets…",
    ),
    "search_media": (
        "Je cherche le film ou la série…",
        "Je consulte la fiche…",
        "Je regarde ce que je trouve…",
    ),
    "search_game": (
        "Je cherche le jeu…",
        "Je consulte la fiche du jeu…",
        "Je regarde sur Steam…",
    ),
    "search_track": (
        "Je cherche le morceau…",
        "Je consulte le titre…",
        "Je regarde l'album…",
    ),
    "search_images": (
        "Je cherche des images…",
        "Je regarde ce qu'il y a comme images…",
        "Je trie des images…",
    ),
    "search_memory": (
        "Je cherche dans mes souvenirs…",
        "Je fouille ma mémoire…",
        "Je vérifie ce que je sais…",
    ),
    "summarize_channel": (
        "Je résume le salon…",
        "Je relis le salon…",
        "Je fais le point sur le salon…",
    ),
    "run_python": (
        "Je lance le calcul…",
        "Je fais tourner le code…",
        "Je vérifie par le calcul…",
    ),
    "calculate": (
        "Je calcule…",
        "Je fais le calcul…",
        "Je vérifie le résultat…",
    ),
    "plot_function": (
        "Je trace la courbe…",
        "Je dessine la courbe…",
        "Je prépare le tracé…",
    ),
    "render_chart": (
        "Je prépare le graphique…",
        "Je dessine le graphique…",
        "Je trace le graphique…",
    ),
    "render_diagram": (
        "Je dessine le schéma…",
        "Je prépare le schéma…",
        "Je mets le schéma en forme…",
    ),
    "render_math": (
        "Je prépare la formule…",
        "Je mets la formule en forme…",
        "Je compose la formule…",
    ),
    "render_qr": (
        "Je génère le QR code…",
        "Je prépare le QR code…",
        "Je fabrique le QR code…",
    ),
}


def default_label(dice: random.Random | None = None) -> str:
    """La phrase quand aucun outil n'est nommé."""
    return (dice or random).choice(_DEFAULT)


def progress_label(names: Sequence[str], avoid: str = "", dice: random.Random | None = None) -> str:
    """Une phrase du premier outil connu du lot, autre que `avoid` (la précédente) si possible."""
    options = next((_LABELS[name] for name in names if name in _LABELS), _DEFAULT)
    fresh = [text for text in options if text != avoid] or list(options)
    return (dice or random).choice(fresh)
