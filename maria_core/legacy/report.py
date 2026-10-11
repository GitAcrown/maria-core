"""Rapport lisible, avant toute écriture."""

from collections import Counter

from maria_core.legacy.model import ImportPlan

GAPS = (
    "À l'écriture, l'index Chroma est recopié et chaque vecteur prend l'identifiant du souvenir.",
    "Une veille de prix se répète tant que le seuil tient.",
    "Une écoute de mot-clé ne reprend pas le filtre d'auteur.",
    "Un signal vocal ou une arrivée ciblée sur une personne n'est pas repris.",
    "Une recherche web ou une comparaison au relevé précédent n'est pas devinée.",
    "Les signets, les fun stats et les statistiques de serveur ne sont pas repris.",
    "L'activité journalière n'est pas répartie sur les heures.",
)


def render(plan: ImportPlan) -> str:
    if plan.missing_root:
        return f"Dossier introuvable : {plan.root}\nAucune écriture."
    lines = [f"Source : {plan.root}", "", *_ready(plan), *_review(plan), *_aside(plan), ""]
    lines.append("Écarts connus :")
    lines.extend(f"  {gap}" for gap in GAPS)
    return "\n".join(lines)


def _ready(plan: ImportPlan) -> list[str]:
    lines = [f"Objectifs prêts : {len(plan.objectives)}"]
    for item in plan.objectives:
        extra = f" — {item.notice}" if item.notice else ""
        kind = str(item.trigger.get("type") or "?")
        lines.append(f"  tâche {item.legacy_id} → {item.status}, {kind}{extra}")
    lines.append(f"Souvenirs prêts : {len(plan.memories)}")
    lines.append(f"Propositions prêtes : {len(plan.proposals)}")
    lines.append(f"Serveurs : {len(plan.guilds)}")
    for item in plan.guilds:
        extra = f" — {item.notice}" if item.notice else ""
        lines.append(f"  serveur {item.guild_id} → {item.mode}{extra}")
    lines.append(f"Salons : {len(plan.channels)}")
    lines.append(f"Emojis : {len(plan.emojis)}")
    lines.append(f"Sondages : {len(plan.polls)}")
    return lines


def _review(plan: ImportPlan) -> list[str]:
    loud = [item for item in plan.skips if item.loud]
    lines = ["", f"À relire : {len(loud)}"]
    lines.extend(f"  {item.source} {item.legacy_id} : {item.reason}" for item in loud)
    return lines


def _aside(plan: ImportPlan) -> list[str]:
    quiet = [item for item in plan.skips if not item.loud]
    lines: list[str] = []
    if quiet:
        counts = Counter(item.reason for item in quiet)
        detail = ", ".join(f"{reason} ({counts[reason]})" for reason in sorted(counts))
        lines.append(f"Laissés de côté : {detail}")
    if plan.ignored:
        lines.append("Ignorés :")
        lines.extend(f"  {item}" for item in plan.ignored)
    if plan.absent:
        lines.append("Absents :")
        lines.extend(f"  {item}" for item in plan.absent)
    return lines
