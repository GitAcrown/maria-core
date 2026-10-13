"""Types livrés avec le noyau. Une extension peut en ajouter."""

from maria_core.objectives.types import ObjectiveKind, ObjectiveTypes

_KINDS = (
    ("trigger", "at", "Une fois, à une date"),
    ("trigger", "daily", "Tous les jours à une heure"),
    ("trigger", "weekly", "Certains jours de la semaine"),
    ("trigger", "interval", "À intervalle régulier"),
    ("trigger", "on_message", "Un message du salon qui remplit une condition jugée"),
    ("trigger", "on_topic", "Quand un message contient un mot, ou parle d'un sujet"),
    ("trigger", "on_voice", "Quand quelqu'un rejoint, quitte un vocal ou lance un stream"),
    ("trigger", "on_member_join", "Quand un membre arrive"),
    ("trigger", "on_reply_to", "Quand on répond à MARIA"),
    ("condition", "price_below", "Le prix est sous un seuil"),
    ("condition", "price_above", "Le prix est au-dessus d'un seuil"),
    ("condition", "price_drop", "Le prix a baissé d'un pourcentage"),
    ("condition", "price_lower", "Le prix est plus bas qu'au passage précédent"),
    ("condition", "price_higher", "Le prix est plus haut qu'au passage précédent"),
    ("condition", "judge", "Un jugement sur un texte"),
    ("condition", "page_changed", "Ce qui compte sur la page a changé"),
    ("action", "remind", "Message envoyé tel quel"),
    ("action", "alert", "Message court à partir d'un gabarit"),
    ("action", "report", "Texte rédigé pour l'échéance"),
    ("action", "fetch_then", "Lire une page ou chercher sur le web, puis décider"),
)


def register_builtin_kinds(types: ObjectiveTypes) -> None:
    for family, name, description in _KINDS:
        kind = ObjectiveKind(name=name, family=family, description=description)
        if family == "trigger":
            types.register_trigger(kind)
        elif family == "condition":
            types.register_condition(kind)
        else:
            types.register_action(kind)
