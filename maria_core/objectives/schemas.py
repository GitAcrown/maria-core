"""Schémas des outils d'objectifs. Chaque valeur permise est listée pour le modèle."""

from typing import Any

TRIGGERS = [
    "at",
    "daily",
    "weekly",
    "interval",
    "on_topic",
    "on_message",
    "on_reply_to",
    "on_voice",
    "on_member_join",
]
ACTIONS = ["remind", "alert", "report", "fetch_then"]
CONDITIONS = [
    "price_below",
    "price_above",
    "price_drop",
    "price_lower",
    "price_higher",
    "judge",
]

GUIDE = (
    "OBJECTIFS : dès qu'on veut être prévenu plus tard, ou qu'on surveille quelque chose, "
    "objective_create dans ce tour.\n"
    "- Heure dite : trigger_type=at avec at en heure de Paris (2026-10-12T20:00), ou in_minutes "
    "pour « dans 10 min ». Récurrent : daily/weekly (time HH:MM, weekdays). interval seulement "
    "pour une veille sans heure (au moins 6 h si elle lit le web).\n"
    "- action_type : remind = le texte tel quel (rappel, ping) ; alert = court message d'écoute ; "
    "report = texte rédigé au moment voulu avec tes outils (météo, résumé, actu, blague) ; "
    "fetch_then = lire url ou chercher query, puis condition, puis message (write=true pour "
    "rédiger).\n"
    "- Prix : condition_type price_below/price_above + threshold, price_drop + threshold en %, "
    "price_lower/price_higher = par rapport au passage précédent. Sinon judge + condition_text ; "
    "condition_when=before juge le déclencheur (le message) avant l'action.\n"
    "- Écoute : on_topic avec pattern (mot cité, variantes séparées par des virgules) ou topic "
    "(sujet flou). « quand JE dis » → author=self. Vocal : on_voice + voice_event "
    "(join/leave/stream) + target_user_id. Une fois par défaut ; repeat=true pour chaque fois.\n"
    "- N'invente ni nombre d'alertes ni durée, ne demande pas « combien de fois ». "
    "Un brouillon part après un oui : objective_update op=confirm. Ajustement : op=modify."
)


def create_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Titre court et distinctif"},
            "trigger_type": {"type": "string", "enum": TRIGGERS},
            "action_type": {"type": "string", "enum": ACTIONS},
            "text": {"type": "string", "description": "Message à envoyer, ou consigne du récap"},
            **_fields(),
        },
        "required": ["title", "trigger_type", "action_type"],
    }


def update_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "op": {
                "type": "string",
                "enum": ["pause", "resume", "cancel", "skip", "confirm", "modify"],
            },
            "title": {"type": "string"},
            "trigger_type": {"type": "string", "enum": TRIGGERS},
            "action_type": {"type": "string", "enum": ACTIONS},
            "text": {"type": "string"},
            **_fields(),
        },
        "required": ["id", "op"],
    }


def _fields() -> dict[str, Any]:
    return {
        "at": {"type": "string", "description": "Date et heure de Paris, 2026-10-12T20:00"},
        "in_minutes": {"type": "integer", "minimum": 1, "description": "Dans N minutes"},
        "time": {"type": "string", "description": "HH:MM, heure de Paris"},
        "weekdays": {"type": "string", "description": "lundi,mercredi ou mon,wed"},
        "every_minutes": {"type": "integer", "minimum": 1},
        "pattern": {"type": "string", "description": "Mot à guetter, variantes après des virgules"},
        "topic": {"type": "string", "description": "Sujet à guetter, en quelques mots"},
        "author": {
            "type": "string",
            "description": "others (défaut), self, any, ou un id Discord",
        },
        "voice_event": {"type": "string", "enum": ["join", "leave", "stream"]},
        "target_user_id": {"type": "string", "description": "Id Discord de la personne guettée"},
        "voice_channel_id": {"type": "string"},
        "repeat": {"type": "boolean", "description": "Écoute répétée au lieu d'une seule fois"},
        "url": {"type": "string", "description": "Page à lire (fetch_then)"},
        "query": {"type": "string", "description": "Recherche web (fetch_then sans url)"},
        "write": {"type": "boolean", "description": "fetch_then : rédiger le message"},
        "condition_type": {"type": "string", "enum": CONDITIONS},
        "condition_text": {"type": "string", "description": "Condition en clair (judge)"},
        "condition_when": {"type": "string", "enum": ["before", "after"]},
        "threshold": {"type": "number", "description": "Seuil en € ou en %"},
        "deliver": {"type": "string", "enum": ["channel", "dm"]},
        "max_fires": {"type": "integer", "minimum": 1},
    }
