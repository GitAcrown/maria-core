"""Erreurs explicites du socle."""


class MariaError(Exception):
    """Erreur métier rattrapable au démarrage ou au chargement d'une extension."""


class ConfigError(MariaError):
    """Configuration absente ou invalide."""


class DatabaseError(MariaError):
    """Base illisible, migration impossible ou appel après fermeture."""


class MigrationError(DatabaseError):
    """Une migration a échoué. La base est revenue à l'état précédent."""


class RegistryError(MariaError):
    """Enregistrement refusé : nom invalide, doublon ou élément inconnu."""


class PluginError(MariaError):
    """Une extension n'a pas pu être chargée ou déchargée."""


class LLMError(MariaError):
    """L'appel au modèle a échoué."""
