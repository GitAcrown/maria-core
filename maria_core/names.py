"""Noms publics : identifiants stables, lisibles dans les journaux."""

import re

from maria_core.errors import RegistryError

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def require_name(value: str, *, what: str) -> str:
    """Valide un identifiant en minuscules (lettres, chiffres, soulignés)."""
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise RegistryError(
            f"{what} invalide : {value!r}. Attendu : minuscules, chiffres et soulignés."
        )
    return value
