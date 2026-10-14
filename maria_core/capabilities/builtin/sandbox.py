"""Exécution Python restreinte. Lancé en sous-processus par run_python."""

import ast
import datetime as dt
import decimal
import json
import math
import re
import statistics
import sys
import types
from io import StringIO
from typing import Any

_MAX_SOURCE = 2000
# Cadres d'exécution, code, générateurs : de là on remonte jusqu'au vrai interpréteur.
_INTERNALS = ("gi_", "cr_", "ag_", "f_", "tb_", "co_", "func_")


class _Public:
    """Une bibliothèque vue du code : ses fonctions et classes, jamais les modules qu'elle importe.

    Sans ça, `statistics.sys.modules` ouvrirait la porte à `os`.
    """

    __slots__ = ("_module",)

    def __init__(self, module: types.ModuleType) -> None:
        object.__setattr__(self, "_module", module)

    def __getattr__(self, name: str) -> Any:
        module = object.__getattribute__(self, "_module")
        value = None if name.startswith("_") else getattr(module, name)
        if value is None or isinstance(value, types.ModuleType):
            raise AttributeError(f"module '{module.__name__}' has no attribute '{name}'")
        return value

    def __dir__(self) -> list[str]:
        return [n for n in dir(object.__getattribute__(self, "_module")) if not n.startswith("_")]


# Déjà disponibles sans import : un `import math` du modèle est inoffensif, on le laisse passer.
_LIBRARIES = {
    "math": math,
    "statistics": statistics,
    "datetime": dt,
    "decimal": decimal,
    "json": json,
    "re": re,
}
_MODULES = {name: _Public(module) for name, module in _LIBRARIES.items()}
# Ce que datetime, re ou decimal importent eux-mêmes en travaillant (date.today(), strptime…).
_INTERNAL = frozenset({"time", "_strptime", "_datetime", "_decimal", "_pydecimal", "locale"})
_NO_IMPORT = "Pas de classe, d'async ni de with ; seuls " + ", ".join(_MODULES) + " existent."

_FORBIDDEN_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "breakpoint",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "__import__",
        "memoryview",
        "exit",
        "quit",
        "help",
        "copyright",
        "credits",
        "license",
        "classmethod",
        "staticmethod",
        "property",
        "super",
        "type",
    }
)

_FORBIDDEN_AST: tuple[type, ...] = (
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
    ast.With,
    ast.AsyncWith,
    ast.AsyncFor,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
    ast.ClassDef,
    ast.AsyncFunctionDef,
    ast.Match,
    ast.TryStar,
)


class _SandboxError(Exception):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


class _Checker(ast.NodeVisitor):
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith(_INTERNALS):
            raise _SandboxError(f"Attribut interdit : .{node.attr}", "Pas d'accès interne.")
        if node.attr.startswith("_") and node.attr != "_result":
            raise _SandboxError(f"Attribut interdit : .{node.attr}", "Pas d'accès interne.")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("_") or node.id in _FORBIDDEN_NAMES:
            raise _SandboxError(f"Nom interdit : {node.id}", "Builtins dangereux bloqués.")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_NAMES:
            raise _SandboxError(f"Appel interdit : {node.func.id}()", "Pas open, eval, getattr.")
        self.generic_visit(node)


def execute(source: str) -> dict[str, Any]:
    """Exécute `source` et renvoie {ok, stdout, result} ou {error, hint}."""
    code = (source or "").strip()
    refused = _refused(code)
    if refused is not None:
        return refused
    try:
        tree = _capture(_validate(code))
        compiled = compile(tree, "<maria>", "exec")
    except _SandboxError as exc:
        return {"error": str(exc), "hint": exc.hint}
    except Exception as exc:
        return {"error": f"Compilation impossible : {exc}", "hint": "Simplifie le script."}
    return _run(compiled)


def main() -> None:
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    sys.stdout.buffer.write(json.dumps(execute(raw), ensure_ascii=False, default=str).encode())


def _refused(code: str) -> dict[str, str] | None:
    if not code:
        return {"error": "Code vide", "hint": "Termine par une expression ou un print()."}
    if len(code) > _MAX_SOURCE:
        return {"error": f"Code trop long ({len(code)} caractères)", "hint": "Coupe le script."}
    return None


def _validate(source: str) -> ast.Module:
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise _SandboxError(
            f"Syntaxe Python invalide : {exc.msg}", "Envoie du Python valide."
        ) from exc
    tree.body = _allowed_imports(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_AST):
            raise _SandboxError(f"Construction interdite : {type(node).__name__}", _NO_IMPORT)
    _Checker().visit(tree)
    ast.fix_missing_locations(tree)
    return tree


def _allowed_imports(body: list[ast.stmt]) -> list[ast.stmt]:
    """`import math` ne fait rien (déjà là) ; `from math import sqrt` devient `sqrt = math.sqrt`."""
    kept: list[ast.stmt] = []
    for node in body:
        if isinstance(node, ast.Import) and all(a.name in _MODULES for a in node.names):
            kept.extend(_bind(alias.asname, alias.name) for alias in node.names if alias.asname)
        elif isinstance(node, ast.ImportFrom) and _from_ok(node):
            kept.append(_bind_from(node))
        else:
            kept.append(node)
    return kept


def _from_ok(node: ast.ImportFrom) -> bool:
    module = _MODULES.get(node.module or "")
    if node.level or module is None:
        return False
    return all(
        alias.name != "*" and not alias.name.startswith("_") and hasattr(module, alias.name)
        for alias in node.names
    )


def _bind(target: str | None, module: str, attribute: str = "") -> ast.stmt:
    value: ast.expr = ast.Name(id=module, ctx=ast.Load())
    if attribute:
        value = ast.Attribute(value=value, attr=attribute, ctx=ast.Load())
    return ast.Assign(targets=[ast.Name(id=target or module, ctx=ast.Store())], value=value)


def _bind_from(node: ast.ImportFrom) -> ast.stmt:
    """Tout est lu avant d'être lié : `from datetime import datetime, timedelta` reste correct."""
    module = node.module or ""
    names = [ast.Name(id=a.asname or a.name, ctx=ast.Store()) for a in node.names]
    values = [
        ast.Attribute(value=ast.Name(id=module, ctx=ast.Load()), attr=a.name, ctx=ast.Load())
        for a in node.names
    ]
    return ast.Assign(
        targets=[ast.Tuple(elts=names, ctx=ast.Store())],
        value=ast.Tuple(elts=values, ctx=ast.Load()),
    )


def _capture(tree: ast.Module) -> ast.Module:
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        tree.body[-1] = ast.Assign(
            targets=[ast.Name(id="_result", ctx=ast.Store())],
            value=tree.body[-1].value,
        )
        ast.fix_missing_locations(tree)
    return tree


def _run(compiled: Any) -> dict[str, Any]:
    namespace = _namespace()
    namespace["_result"] = None
    buffer = StringIO()
    previous = sys.stdout
    try:
        sys.stdout = buffer
        exec(compiled, namespace, namespace)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "hint": "Corrige l'erreur."}
    finally:
        sys.stdout = previous
    return _payload(buffer.getvalue(), namespace.get("_result"))


def _payload(stdout: str, result: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": True}
    if stdout:
        payload["stdout"] = stdout[:4000]
    if result is not None:
        payload["result"] = _jsonable(result)
    if len(payload) == 1:
        payload["hint"] = "Rien à afficher : utilise print(...) ou termine par une expression."
    return payload


def _jsonable(result: Any) -> Any:
    try:
        json.dumps(result)
    except (TypeError, ValueError):
        return repr(result)[:2000]
    return result


def _guarded_import(
    name: str,
    globals: Any = None,
    locals: Any = None,
    fromlist: Any = (),
    level: int = 0,
) -> Any:
    """Le code ne peut pas écrire `import` ; seules les bibliothèques le font, pour elles-mêmes."""
    root = name.split(".", 1)[0]
    if level == 0 and (root in _MODULES or root in _INTERNAL):
        return __import__(name, globals, locals, fromlist, level)
    raise ImportError(f"Import interdit : {name}")


def _namespace() -> dict[str, Any]:
    builtins = {
        "abs": abs,
        "min": min,
        "max": max,
        "sum": sum,
        "round": round,
        "len": len,
        "range": range,
        "enumerate": enumerate,
        "zip": zip,
        "sorted": sorted,
        "reversed": reversed,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "set": set,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "print": print,
        "isinstance": isinstance,
        "pow": pow,
        "divmod": divmod,
        "all": all,
        "any": any,
        "map": map,
        "filter": filter,
        "repr": repr,
        "hex": hex,
        "oct": oct,
        "bin": bin,
        "chr": chr,
        "ord": ord,
        "True": True,
        "False": False,
        "None": None,
        "__import__": _guarded_import,
    }
    return {"__builtins__": builtins, **_MODULES}


if __name__ == "__main__":
    main()
