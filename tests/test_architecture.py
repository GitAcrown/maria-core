"""Règles d'architecture : taille, imports, frontières entre paquets."""

import ast
import subprocess
import sys
from pathlib import Path

from maria_core import __version__

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "maria_core"
MAX_LINES = 500

_DISCORD_LIBRARY = "discord"
_PACKAGE_ADAPTER = "maria_core.discord"
_THIRD_PARTIES = {
    "openai": ("maria_core/llm/",),
    "typesafe_sdk": ("maria_core/decisions/",),
    "chromadb": ("maria_core/vectors/",),
}


def test_version_matches_project() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in text


def test_files_stay_small() -> None:
    too_long = [
        f"{_relative(path)} ({len(path.read_text(encoding='utf-8').splitlines())} lignes)"
        for path in _python_files()
        if len(path.read_text(encoding="utf-8").splitlines()) > MAX_LINES
    ]
    assert too_long == []


def test_imports_stay_at_module_level() -> None:
    offenders = [
        f"{_relative(path)}:{line}" for path in _python_files() for line in _nested_imports(path)
    ]
    assert offenders == []


def test_private_names_stay_inside_their_object() -> None:
    offenders = [
        f"{_relative(path)}:{line}"
        for path in _python_files()
        for line in _private_accesses(path) + _private_imports(path)
    ]
    assert offenders == []


def test_discord_and_model_sdks_stay_in_their_packages() -> None:
    offenders: list[str] = []
    for path in _python_files():
        relative = _relative(path)
        for imported in _imported_modules(path):
            if not _import_allowed(relative, imported):
                offenders.append(f"{relative} importe {imported}")
    assert offenders == []


def test_ruff_is_clean() -> None:
    check = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "maria_core", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    formatting = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "maria_core", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert formatting.returncode == 0, formatting.stdout + formatting.stderr


def _python_files() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _nested_imports(path: Path) -> list[int]:
    found: list[int] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.depth = 0

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._enter(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._enter(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._enter(node)

        def visit_Import(self, node: ast.Import) -> None:
            if self.depth:
                found.append(node.lineno)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if self.depth:
                found.append(node.lineno)

        def _enter(self, node: ast.AST) -> None:
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

    Visitor().visit(_parse(path))
    return found


def _private_accesses(path: Path) -> list[int]:
    found: list[int] = []

    class Visitor(ast.NodeVisitor):
        def visit_Attribute(self, node: ast.Attribute) -> None:
            if _is_private(node.attr) and not _is_self(node.value):
                found.append(node.lineno)
            self.generic_visit(node)

    Visitor().visit(_parse(path))
    return found


def _private_imports(path: Path) -> list[int]:
    found: list[int] = []
    for node in ast.walk(_parse(path)):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if _is_private(alias.name):
                found.append(node.lineno)
    return found


def _imported_modules(path: Path) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _import_allowed(relative: str, imported: str) -> bool:
    root = imported.split(".", 1)[0]
    if root == _DISCORD_LIBRARY or imported.startswith(f"{_PACKAGE_ADAPTER}."):
        return relative.startswith("maria_core/discord/") or relative == "maria_core/__main__.py"
    if imported == _PACKAGE_ADAPTER:
        return relative.startswith("maria_core/discord/") or relative == "maria_core/__main__.py"
    for library, allowed in _THIRD_PARTIES.items():
        if root == library and not relative.startswith(allowed):
            return False
    return True


def _is_private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _is_self(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id in {"self", "cls"}
