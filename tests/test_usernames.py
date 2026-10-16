"""Les interfaces montrent le nom d'utilisateur (`.name`), jamais le pseudo d'affichage."""

from pathlib import Path

# Seules lectures permises : retrouver quelqu'un par n'importe lequel de ses noms.
_ALLOWED = {
    "maria_core/discord/directory.py": 2,  # recherche d'un membre par pseudo ou nom
    "maria_core/discord/inbound.py": 1,  # les noms sous lesquels on appelle MARIA
}


def test_ui_code_never_shows_the_display_name() -> None:
    root = Path(__file__).resolve().parents[1]
    found: dict[str, int] = {}
    for path in (root / "maria_core").rglob("*.py"):
        count = path.read_text(encoding="utf-8").count("display_name")
        if count:
            found[path.relative_to(root).as_posix()] = count
    assert found == _ALLOWED
