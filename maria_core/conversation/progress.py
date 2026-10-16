"""Ce que MARIA annonce quand un outil tarde : précisément, et jamais deux fois pareil."""

import random
import re
from collections.abc import Sequence
from urllib.parse import urlparse

from maria_core.llm.types import ToolCall

DELAY_S = 2.0
_DETAIL_CHARS = 48
_DEFAULT = ("Je m'en occupe…", "Je regarde ça…", "Je m'y mets…")

# Sans précision : une phrase par outil, au moins trois formulations.
_LABELS: dict[str, tuple[str, ...]] = {
    "search_web": (
        "Je cherche sur le web…",
        "Je lance une recherche…",
        "Je regarde ce qu'on trouve en ligne…",
    ),
    "read_web_page": ("Je lis la page…", "J'ouvre la page…", "Je parcours le contenu de la page…"),
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
    "search_game": ("Je cherche le jeu…", "Je consulte la fiche du jeu…", "Je regarde sur Steam…"),
    "search_track": ("Je cherche le morceau…", "Je consulte le titre…", "Je regarde l'album…"),
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
    "run_python": ("Je lance le calcul…", "Je fais tourner le code…", "Je vérifie par le calcul…"),
    "calculate": ("Je calcule…", "Je fais le calcul…", "Je vérifie le résultat…"),
    "plot_function": ("Je trace la courbe…", "Je dessine la courbe…", "Je prépare le tracé…"),
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
    "render_qr": ("Je génère le QR code…", "Je prépare le QR code…", "Je fabrique le QR code…"),
}

# Avec précision : l'argument à citer (`d`), puis des phrases qui le contiennent.
_DETAILED: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "search_web": (
        ("query",),
        (
            "Je cherche « {d} »…",
            "Recherche : « {d} »…",
            "Je lance la recherche « {d} »…",
        ),
    ),
    "read_web_page": (
        ("url",),
        ("Je lis {d}…", "J'ouvre {d}…", "Lecture de {d}…"),
    ),
    "get_weather": (
        ("city",),
        (
            "Je consulte la météo de {d}…",
            "Prévisions pour {d}…",
            "Je vérifie le temps à {d}…",
        ),
    ),
    "get_football": (
        ("team",),
        (
            "Je consulte les scores de {d}…",
            "Je vérifie les résultats de {d}…",
            "Je regarde le match de {d}…",
        ),
    ),
    "get_transport": (
        ("stop",),
        (
            "Je consulte les horaires à {d}…",
            "Prochains passages à {d}…",
            "Je vérifie les trajets depuis {d}…",
        ),
    ),
    "search_media": (
        ("query",),
        (
            "Je cherche « {d} » (film ou série)…",
            "Je consulte la fiche de « {d} »…",
            "Recherche : « {d} »…",
        ),
    ),
    "search_game": (
        ("query",),
        (
            "Je cherche « {d} » sur Steam…",
            "Je consulte la fiche de « {d} »…",
            "Recherche : « {d} »…",
        ),
    ),
    "search_track": (
        ("query",),
        (
            "Je cherche « {d} » sur Spotify…",
            "Je consulte le titre « {d} »…",
            "Recherche : « {d} »…",
        ),
    ),
    "search_images": (
        ("query",),
        (
            "Je cherche des images de « {d} »…",
            "Je trie des images de « {d} »…",
            "Recherche d'images : « {d} »…",
        ),
    ),
    "search_memory": (
        ("query",),
        (
            "Je cherche « {d} » dans mes souvenirs…",
            "Je fouille ma mémoire : « {d} »…",
            "Je vérifie ce que je sais sur « {d} »…",
        ),
    ),
}
_UNSAFE = re.compile(r"[*_~|`<>\[\]()@#\n\r\t]")


def default_label(dice: random.Random | None = None) -> str:
    """La phrase quand aucun outil n'est nommé."""
    return (dice or random).choice(_DEFAULT)


def progress_label(
    calls: Sequence[ToolCall], avoid: str = "", dice: random.Random | None = None
) -> str:
    """La phrase du premier outil connu du lot, autre que `avoid` (la précédente) si possible.

    Un seul appel à un outil qui sait quoi citer : la phrase dit la recherche faite, le site lu,
    la ville consultée. Plusieurs appels, ou rien à citer : la phrase générale de l'outil.
    """
    known = next((call for call in calls if call.name in _LABELS), None)
    options: tuple[str, ...] = _DEFAULT
    if known is not None:
        options = _LABELS[known.name]
        detail = _detail(known) if len(calls) == 1 else ""
        if detail:
            options = tuple(template.format(d=detail) for template in _DETAILED[known.name][1])
    fresh = [text for text in options if text != avoid] or list(options)
    return (dice or random).choice(fresh)


def _detail(call: ToolCall) -> str:
    """Ce que l'outil travaille, propre : sans mise en forme, court, domaine pour une adresse."""
    if call.name not in _DETAILED:
        return ""
    for key in _DETAILED[call.name][0]:
        raw = str(call.arguments.get(key) or "").strip()
        if raw:
            return _site(raw) if key == "url" else _short(raw)
    return ""


def _site(url: str) -> str:
    host = (urlparse(url if "//" in url else f"//{url}").netloc or "").lower()
    return _short(host.removeprefix("www."))


def _short(text: str) -> str:
    plain = " ".join(_UNSAFE.sub(" ", text).split())
    if len(plain) <= _DETAIL_CHARS:
        return plain
    return plain[: _DETAIL_CHARS - 1].rstrip() + "…"
