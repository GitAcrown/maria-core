"""Graphiques, diagrammes, QR codes et formules, dessinés par des services gratuits.

Rien n'est dessiné sur le serveur : on décrit, un service rend l'image, Discord l'affiche depuis
son adresse. Chaque adresse est vérifiée avant d'être montrée : un service qui refuse (diagramme
mal écrit, formule invalide) renvoie son message à MARIA, qui corrige et réessaie.
"""

import base64
import json
import re
import urllib.parse
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from maria_core.capabilities.base import Capability, Context, Result, Risk
from maria_core.capabilities.http import HttpClient, HttpError
from maria_core.ui.emojis import VISUAL_ICONS
from maria_core.ui.widgets import Rendered, card, footer, gallery, separator, text

QUICKCHART = "https://quickchart.io"
_MERMAID = "https://mermaid.ink/img/"
_KROKI = "https://kroki.io/{kind}/png/"
_CODECOGS = "https://latex.codecogs.com/png.latex?"
_URL_LIMIT = 1900
_MAX_IMAGE = 4_000_000
_TIMEOUT = 30
PALETTE = (
    "#4c78a8",
    "#f58518",
    "#54a24b",
    "#e45756",
    "#72b7b2",
    "#eeca3b",
    "#b279a2",
    "#ff9da6",
    "#9d755d",
    "#bab0ac",
)
_ROUND = frozenset({"pie", "doughnut", "polarArea"})
_RADIAL = frozenset({"radar", "polarArea"})
_COLOR = re.compile(r"^(#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20})$")
THEMES = ("light", "dark", "transparent")


@dataclass(frozen=True, slots=True)
class Look:
    """Fond, texte et grille d'une image. « transparent » suppose un Discord sombre."""

    name: str
    background: str
    text: str
    grid: str


_LOOKS = {
    "light": Look("light", "white", "#222222", "#d9d9d9"),
    "dark": Look("dark", "#2b2d31", "#f2f3f5", "#4e5058"),
    "transparent": Look("transparent", "transparent", "#f2f3f5", "#80848e"),
}


def look_of(theme: object) -> Look:
    return _LOOKS.get(str(theme or "light"), _LOOKS["light"])


def palette_of(colors: object) -> tuple[str, ...]:
    """Les couleurs demandées d'abord, puis la palette par défaut pour compléter."""
    asked = [str(item).strip() for item in colors or [] if str(item).strip()][:10]
    for item in asked:
        if not _COLOR.match(item):
            raise ValueError(f"Couleur illisible : {item}. Écris red, #ff8800…")
    return (*asked, *PALETTE)


def look_options(kind: str, look: Look) -> dict[str, Any]:
    """Texte, légende et grilles dans les couleurs du thème, pour rester lisible."""
    options: dict[str, Any] = {
        "legend": {"labels": {"fontColor": look.text}},
        "title": {"fontColor": look.text},
    }
    if kind in _RADIAL:
        options["scale"] = {
            "ticks": {"fontColor": look.text, "backdropColor": "transparent"},
            "gridLines": {"color": look.grid},
            "angleLines": {"color": look.grid},
            "pointLabels": {"fontColor": look.text},
        }
    elif kind not in _ROUND:
        axis = {"ticks": {"fontColor": look.text}, "gridLines": {"color": look.grid}}
        options["scales"] = {"xAxes": [axis], "yAxes": [axis]}
    return options


CHART_TYPES = ("bar", "horizontalBar", "line", "pie", "doughnut", "radar", "polarArea")
DIAGRAMS = ("mermaid", "graphviz", "plantuml")
_SERVICES = {
    "chart": "QuickChart",
    "diagram": "mermaid.ink",
    "graphviz": "Kroki",
    "plantuml": "Kroki",
    "qr": "QuickChart",
    "math": "CodeCogs",
    "plot": "QuickChart",
}


def visual_capabilities(http: HttpClient) -> tuple[Capability, ...]:
    return (
        _tool("render_chart", _CHART_TEXT, _chart_schema(), _chart(http), 600),
        _tool("render_diagram", _DIAGRAM_TEXT, _diagram_schema(), _diagram(http), 3600),
        _tool("render_qr", _QR_TEXT, _qr_schema(), _qr(http), 3600),
        _tool("render_math", _MATH_TEXT, _math_schema(), _math(http), 3600),
    )


def render_visual(data: Mapping[str, Any]) -> Rendered:
    """Titre, trait, image, service d'origine : comme les autres cartes."""
    kind = str(data.get("kind") or "")
    icon = VISUAL_ICONS.get(kind, "🖼️")
    title = str(data.get("title") or "").strip()
    head = f"## {icon} {title}" if title else f"## {icon}"
    built = card(
        text(head),
        separator(wide=True),
        gallery([str(data.get("url") or "")]),
        footer(f"{_SERVICES.get(str(data.get('service') or kind), kind)} · image générée"),
    )
    return Rendered(cards=(built,), note=f"Image affichée : {title or kind}.")


def shown(kind: str, title: str, url: str, service: str = "") -> Result:
    data = {"kind": kind, "title": title, "url": url, "service": service or kind}
    return Result(ok=True, data=data, widget="render_visual")


async def verify(http: HttpClient, url: str) -> str:
    """Vide si l'image est servie ; sinon le message du service, utile pour corriger."""
    try:
        response = await http.request("GET", url, timeout=_TIMEOUT, max_bytes=_MAX_IMAGE)
    except HttpError as exc:
        return f"Service injoignable : {exc}"
    kind = next((v for k, v in response.headers.items() if k.lower() == "content-type"), "")
    if response.status == 200 and kind.lower().startswith("image/"):
        return ""
    detail = response.body[:300].decode("utf-8", errors="replace").strip()
    why = f" : {detail}" if detail else ""
    return f"Le service a refusé l'image (HTTP {response.status}){why}"


async def chart_url(http: HttpClient, config: Mapping[str, Any], background: str = "white") -> str:
    """Adresse courte d'un graphique Chart.js ; lève ValueError avec le message du service."""
    body = json.dumps(
        {
            "chart": config,
            "width": 720,
            "height": 420,
            "backgroundColor": background,
            "format": "png",
            "version": "2",
        }
    ).encode("utf-8")
    try:
        response = await http.request(
            "POST",
            f"{QUICKCHART}/chart/create",
            headers={"Content-Type": "application/json"},
            body=body,
            timeout=_TIMEOUT,
        )
        payload = json.loads(response.body.decode("utf-8"))
    except (HttpError, ValueError) as exc:
        raise ValueError(f"QuickChart injoignable : {exc}") from exc
    url = payload.get("url") if isinstance(payload, dict) else None
    if response.status != 200 or not url:
        raise ValueError(f"QuickChart a refusé le graphique : {str(payload)[:200]}")
    return str(url)


def _chart(http: HttpClient) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        try:
            config = chart_config(args)
            url = await chart_url(http, config, look_of(args.get("theme")).background)
        except ValueError as exc:
            return Result(ok=False, data={}, error=str(exc))
        return shown("chart", str(args.get("title") or "").strip(), url)

    return run


def chart_config(args: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(args["type"])
    labels = [str(item)[:40] for item in args["labels"]][:30]
    datasets = [item for item in args["datasets"] if isinstance(item, Mapping)][:4]
    if not labels or not datasets:
        raise ValueError("Il faut des étiquettes (labels) et au moins une série (datasets).")
    colors = palette_of(args.get("colors"))
    built = [
        _dataset(kind, index, item, len(labels), colors) for index, item in enumerate(datasets)
    ]
    title = str(args.get("title") or "").strip()
    options = look_options(kind, look_of(args.get("theme")))
    options["title"] |= {"display": bool(title), "text": title, "fontSize": 18}
    options["legend"]["display"] = len(built) > 1 or kind in _ROUND
    return {"type": kind, "data": {"labels": labels, "datasets": built}, "options": options}


def _dataset(
    kind: str, index: int, raw: Mapping[str, Any], count: int, colors: tuple[str, ...]
) -> dict[str, Any]:
    values = [_number(item) for item in raw.get("data") or []]
    if len(values) != count:
        raise ValueError(
            f"La série « {raw.get('label')} » a {len(values)} valeurs pour {count} étiquettes."
        )
    color = colors[index % len(colors)]
    built: dict[str, Any] = {"label": str(raw.get("label") or f"Série {index + 1}")[:40]}
    built["data"] = values
    if kind in _ROUND:
        built["backgroundColor"] = [colors[i % len(colors)] for i in range(count)]
    elif kind in {"line", "radar"}:
        built.update(borderColor=color, backgroundColor=color + "33", fill=kind == "radar")
    else:
        built["backgroundColor"] = color
    return built


def _number(value: Any) -> float | int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Les valeurs d'une série doivent être des nombres.")
    return value


def _diagram(http: HttpClient) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        kind, code = str(args["kind"]), str(args["code"]).strip()
        try:
            url = diagram_url(kind, code, look_of(args.get("theme")))
        except ValueError as exc:
            return Result(ok=False, data={}, error=str(exc))
        problem = await verify(http, url)
        if problem:
            return Result(ok=False, data={}, error=f"Diagramme {kind} : {problem}")
        service = "diagram" if kind == "mermaid" else kind
        return shown("diagram", str(args.get("title") or "").strip(), url, service)

    return run


def diagram_url(kind: str, code: str, look: Look | None = None) -> str:
    if kind not in DIAGRAMS:
        raise ValueError(f"Type de diagramme inconnu : {kind}. Au choix : {', '.join(DIAGRAMS)}.")
    if not code:
        raise ValueError("Diagramme vide.")
    look = look or _LOOKS["light"]
    if kind == "mermaid":
        data = code.encode("utf-8")
        url = _MERMAID + base64.urlsafe_b64encode(data).decode() + _mermaid_style(look)
    else:
        styled = (_graphviz_style if kind == "graphviz" else _plantuml_style)(code, look)
        packed = base64.urlsafe_b64encode(zlib.compress(styled.encode("utf-8"), 9)).decode()
        url = _KROKI.format(kind=kind) + packed
    if len(url) > _URL_LIMIT:
        raise ValueError("Diagramme trop gros : simplifie-le (moins de nœuds ou de texte).")
    return url


def _mermaid_style(look: Look) -> str:
    """mermaid.ink : sans bgColor le fond est transparent ; « ! » devant un nom de couleur."""
    if look.name == "dark":
        return "?type=png&theme=dark&bgColor=2b2d31"
    if look.name == "transparent":
        return "?type=png&theme=dark"
    return "?type=png&theme=default&bgColor=!white"


def _graphviz_style(code: str, look: Look) -> str:
    """Fond, texte et traits du thème, posés avant le dessin de la personne (qui reste maître)."""
    if "{" not in code:
        return code
    line = (
        f' bgcolor="{look.background}"; fontcolor="{look.text}";'
        f' node [fontcolor="{look.text}", color="{look.text}"];'
        f' edge [fontcolor="{look.text}", color="{look.text}"]; '
    )
    head, _, rest = code.partition("{")
    return f"{head}{{{line}{rest}"


def _plantuml_style(code: str, look: Look) -> str:
    if look.name == "light":
        return code
    skin = [
        f"skinparam backgroundColor {look.background}",
        *(
            f"skinparam {name} {look.text}"
            for name in (
                "defaultFontColor",
                "ArrowColor",
                "ArrowFontColor",
                "ParticipantFontColor",
                "ParticipantBorderColor",
                "SequenceLifeLineBorderColor",
                "ActorFontColor",
                "ActorBorderColor",
                "NoteFontColor",
            )
        ),
        "skinparam ParticipantBackgroundColor #2b2d31",
        "skinparam ActorBackgroundColor #2b2d31",
    ]
    first, _, rest = code.partition("\n")
    if not first.lstrip().startswith("@start"):
        return code
    return first + "\n" + "\n".join(skin) + "\n" + rest


def _qr(http: HttpClient) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        content = str(args["text"]).strip()
        if not content or len(content) > 500:
            return Result(ok=False, data={}, error="Le QR code accepte 1 à 500 caractères.")
        query = urllib.parse.urlencode({"text": content, "size": 400, "margin": 2})
        url = f"{QUICKCHART}/qr?{query}"
        problem = await verify(http, url)
        if problem:
            return Result(ok=False, data={}, error=f"QR code : {problem}")
        return shown("qr", str(args.get("title") or "QR code"), url)

    return run


def _math(http: HttpClient) -> Callable[[Context, Mapping[str, Any]], Any]:
    async def run(_context: Context, args: Mapping[str, Any]) -> Result:
        formula = str(args["latex"]).strip()
        if not formula or len(formula) > 400:
            return Result(ok=False, data={}, error="La formule accepte 1 à 400 caractères.")
        url = _CODECOGS + urllib.parse.quote("\\dpi{220}\\bg{white} " + formula, safe="")
        problem = await verify(http, url)
        if problem:
            return Result(ok=False, data={}, error=f"Formule : {problem}")
        return shown("math", str(args.get("title") or "").strip(), url)

    return run


def _tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    run: Callable[[Context, Mapping[str, Any]], Any],
    cache: float,
) -> Capability:
    return Capability(
        name=name,
        description=description,
        parameters=parameters,
        risk=Risk.EXTERNAL,
        run=run,
        cache_s=cache,
        timeout_s=45,
    )


_THEME_TEXT = (
    "light (fond blanc, défaut), dark (fond sombre, texte clair) ou transparent (texte clair, "
    "pour un Discord sombre). Choisis-le quand on demande un fond, du contraste ou un style."
)
_STYLE_TEXT = (
    "theme : " + _THEME_TEXT + " colors : couleurs voulues (red, #ff8800), dans l'ordre des "
    "séries ou des parts."
)
_CHART_TEXT = (
    "Dessine un graphique (barres, courbe, camembert…) à partir de chiffres donnés. À utiliser "
    "dès qu'on demande un graphique, un camembert, une comparaison en image. labels = les "
    "catégories ; datasets = une ou plusieurs séries, chacune avec autant de valeurs que de "
    "labels. Le graphique EST la réponse : commente-le en une phrase, ne recopie pas les chiffres. "
    + _STYLE_TEXT
)
_DIAGRAM_TEXT = (
    "Dessine un diagramme à partir de son code : mermaid (organigramme graph TD, séquence, "
    "gantt, timeline, mindmap), graphviz (DOT), plantuml. Écris un code court et valide. Si le "
    "service refuse, lis son message, corrige et réessaie une fois. theme : " + _THEME_TEXT
)
_QR_TEXT = "Crée un QR code pour un lien ou un texte (500 caractères au plus)."
_MATH_TEXT = (
    "Affiche une formule mathématique en image à partir de LaTeX, sans $ autour "
    "(\\frac{a}{b}, \\sqrt{x}, \\int_0^1 x^2 dx…). Pour une équation difficile à lire en texte."
)


def _chart_schema() -> dict[str, Any]:
    series = {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "data": {"type": "array", "items": {"type": "number"}, "maxItems": 30},
        },
        "required": ["label", "data"],
    }
    return {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": list(CHART_TYPES)},
            "title": {"type": "string"},
            "labels": {"type": "array", "items": {"type": "string"}, "maxItems": 30},
            "datasets": {"type": "array", "items": series, "minItems": 1, "maxItems": 4},
            "theme": {"type": "string", "enum": list(THEMES)},
            "colors": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        },
        "required": ["type", "labels", "datasets"],
    }


def _diagram_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(DIAGRAMS)},
            "code": {"type": "string", "description": "Code du diagramme, 1500 caractères au plus"},
            "title": {"type": "string"},
            "theme": {"type": "string", "enum": list(THEMES)},
        },
        "required": ["kind", "code"],
    }


def _qr_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"text": {"type": "string"}, "title": {"type": "string"}},
        "required": ["text"],
    }


def _math_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"latex": {"type": "string"}, "title": {"type": "string"}},
        "required": ["latex"],
    }
