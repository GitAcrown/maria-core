"""Évalue une formule en x (sin(x)/x, x^2 - 3*x + 1…) sans jamais appeler eval.

Seuls les nombres, x, quelques constantes, les opérations usuelles et une liste fermée de fonctions
mathématiques sont compris : tout le reste est refusé avant le moindre calcul.
"""

import ast
import math
import operator
from collections.abc import Callable
from typing import Any

MAX_LENGTH = 120
_MAX_POWER = 100
_FUNCTIONS: dict[str, Callable[..., float]] = {
    name: getattr(math, name)
    for name in (
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "sinh",
        "cosh",
        "tanh",
        "exp",
        "log",
        "log10",
        "log2",
        "sqrt",
        "floor",
        "ceil",
    )
}
_FUNCTIONS["abs"] = abs
_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def compile_formula(source: str) -> Callable[[float], float]:
    """Fonction de x. Lève ValueError si la formule sort du cadre."""
    cleaned = (source or "").strip().replace("^", "**").replace("²", "**2").replace("³", "**3")
    if not cleaned or len(cleaned) > MAX_LENGTH:
        raise ValueError(f"Formule vide ou trop longue (au plus {MAX_LENGTH} caractères).")
    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Formule illisible : {cleaned}. Écris par exemple 2*x + sin(x).") from exc
    _check(tree.body)
    return lambda x: float(_value(tree.body, x))


def _check(node: ast.AST) -> None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            raise ValueError("Seuls les nombres sont acceptés.")
    elif isinstance(node, ast.Name):
        if node.id != "x" and node.id not in _CONSTANTS:
            raise ValueError(f"Nom inconnu : {node.id}. Variable x, constantes pi, e, tau.")
    elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        _check(node.left)
        _check(node.right)
    elif isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        _check(node.operand)
    elif isinstance(node, ast.Call):
        _check_call(node)
    else:
        raise ValueError(f"Construction non acceptée : {type(node).__name__}.")


def _check_call(node: ast.Call) -> None:
    name = node.func.id if isinstance(node.func, ast.Name) else ""
    if name not in _FUNCTIONS or node.keywords or len(node.args) != 1:
        raise ValueError(f"Fonction non acceptée. Au choix : {', '.join(sorted(_FUNCTIONS))}.")
    _check(node.args[0])


def _value(node: ast.AST, x: float) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return x if node.id == "x" else _CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp):
        return _UNARY[type(node.op)](_value(node.operand, x))
    if isinstance(node, ast.Call):
        return _FUNCTIONS[node.func.id](_value(node.args[0], x))  # type: ignore[attr-defined]
    return _binary(node, x)  # type: ignore[arg-type]


def _binary(node: ast.BinOp, x: float) -> Any:
    left, right = _value(node.left, x), _value(node.right, x)
    if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POWER:
        raise OverflowError("puissance trop grande")
    return _BINARY[type(node.op)](left, right)
