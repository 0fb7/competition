"""Restricted execution of team-submitted Python strategy code.

Team scripts must define:

    def decide(friendly, enemies, api):
        ...

`friendly` and `enemies` are read-only snapshot dicts (see ship.Ship.snapshot).
`api` exposes the only actions available to a ship (see engine/api.py).

This is a *sandboxed-function* model, not process isolation: code runs
in-process inside a restricted namespace with a whitelisted AST and
whitelisted builtins. It stops accidental misuse and obviously malicious
code (imports, file/network access, dunder poking) but is not a hard
security boundary — don't run untrusted code from strangers with this
alone. Swap in subprocess/container isolation before that's a requirement.
"""

import ast
import math
import re

# node types that are always allowed
_ALLOWED_NODES = {
    ast.Module, ast.FunctionDef, ast.Return, ast.Assign, ast.AugAssign,
    ast.AnnAssign, ast.Expr, ast.Call, ast.Name, ast.Load, ast.Store,
    ast.Constant, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
    ast.If, ast.For, ast.While, ast.Break, ast.Continue, ast.Pass,
    ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript, ast.Slice,
    ast.Index, ast.Attribute, ast.arguments, ast.arg, ast.Add, ast.Sub,
    ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd,
    ast.Not, ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt,
    ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot, ast.IfExp, ast.ListComp,
    ast.comprehension, ast.keyword, ast.Starred, ast.JoinedStr, ast.FormattedValue,
}

_FORBIDDEN_NAMES = {
    "__import__", "eval", "exec", "compile", "open", "input", "globals",
    "locals", "vars", "dir", "getattr", "setattr", "delattr", "help",
    "exit", "quit", "breakpoint",
}

_SAFE_BUILTINS = {
    "abs": abs, "min": min, "max": max, "len": len, "range": range,
    "enumerate": enumerate, "sorted": sorted, "sum": sum, "round": round,
    "int": int, "float": float, "bool": bool, "str": str, "list": list,
    "dict": dict, "tuple": tuple, "set": set, "zip": zip, "map": map,
    "filter": filter, "any": any, "all": all, "True": True, "False": False,
    "None": None,
}

_SAFE_MATH = {
    "sqrt": math.sqrt, "hypot": math.hypot, "atan2": math.atan2,
    "sin": math.sin, "cos": math.cos, "pi": math.pi, "radians": math.radians,
    "degrees": math.degrees,
}

# Final Product Audit fix: str.format()/str.format_map()'s replacement-
# field mini-language ("{0.__class__.__mro__[1].__subclasses__}") does
# dotted attribute access at RUNTIME, parsed from the string's own text —
# it never appears as an ast.Attribute node, so the literal dunder check
# above (line ~node.attr.startswith("__")) never sees it. This is a real,
# independently-reproduced bypass of that check (does not by itself reach
# eval/exec/open or file access — format() only ever returns a string,
# and there is no ast.ClassDef in _ALLOWED_NODES to build a callable
# gadget — but it does leak internal interpreter object state as text,
# which the sandbox's own "dunder poking" claim says it blocks).
#
# Scoped narrowly to the actual attack shape (a "{...}" replacement field
# containing a dotted dunder attribute access) rather than "any string
# containing __", so ordinary log/status strings — including ones that
# happen to contain a double underscore, or ordinary "{team_name}"-style
# replacement fields — are never flagged.
_DUNDER_FORMAT_PATTERN = re.compile(r"\{[^{}]*\.__\w+")


def _string_has_dunder_format_bypass(value: str) -> bool:
    return bool(_DUNDER_FORMAT_PATTERN.search(value))


class SandboxError(Exception):
    pass


def _iter_issues(tree: ast.AST, allowed_api: list[str] | None = None):
    """Single shared AST scan behind both validate_source() (raises on the
    first issue) and collect_validation_issues() (submissions/ — Phase 3,
    returns every issue as structured data). Not a second validator: the
    same checks, exposed two ways.

    `allowed_api`, when given, additionally flags `api["some_name"]`
    subscripts (the calling convention every team script uses — see
    engine/api.py's build_api()) where "some_name" isn't in the list, so
    a Challenge's allowed_api can be checked statically before a battle
    ever runs it.
    """
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODES:
            yield ("disallowed_syntax", f"disallowed syntax: {type(node).__name__}", getattr(node, "lineno", None), getattr(node, "col_offset", None))
            continue
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            yield ("dunder_access", "dunder attribute access is not allowed", node.lineno, node.col_offset)
        if (
            isinstance(node, ast.Constant) and isinstance(node.value, str)
            and _string_has_dunder_format_bypass(node.value)
        ):
            yield (
                "dunder_format_bypass",
                "format-string dunder attribute access is not allowed",
                node.lineno, node.col_offset,
            )
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            yield ("forbidden_name", f"use of '{node.id}' is not allowed", node.lineno, node.col_offset)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield ("forbidden_import", "imports are not allowed", node.lineno, node.col_offset)
        if allowed_api is not None and isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "api":
            key_node = node.slice
            if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                if key_node.value not in allowed_api:
                    yield (
                        "forbidden_api",
                        f"'{key_node.value}()' is not allowed by this challenge",
                        node.lineno, node.col_offset,
                    )


def validate_source(code: str, allowed_api: list[str] | None = None) -> None:
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        raise SandboxError(f"syntax error: {e}") from e

    for _kind, message, _line, _col in _iter_issues(tree, allowed_api):
        raise SandboxError(message)


def collect_validation_issues(code: str, allowed_api: list[str] | None = None) -> list[dict]:
    """Non-raising view of the exact same checks validate_source() uses —
    returns EVERY issue found (not just the first), each as a structured
    dict {type, message, line, column} for submissions/ to store and the
    UI to render without exposing a raw stack trace."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return [{"type": "syntax_error", "message": str(e.msg), "line": e.lineno, "column": e.offset}]
    return [
        {"type": kind, "message": message, "line": line, "column": col}
        for kind, message, line, col in _iter_issues(tree, allowed_api)
    ]


def compile_team_module(code: str):
    """Validates and loads a team script, returning its decide() callable."""
    validate_source(code)

    sandbox_globals = {
        "__builtins__": dict(_SAFE_BUILTINS),
        **_SAFE_MATH,
    }
    try:
        exec(compile(code, "<team_code>", "exec"), sandbox_globals)
    except Exception as e:
        raise SandboxError(f"error loading team code: {e}") from e

    decide = sandbox_globals.get("decide")
    if not callable(decide):
        raise SandboxError("team code must define def decide(friendly, enemies, api)")
    return decide


def run_decide(decide_fn, friendly: dict, enemies: list, api: dict) -> str:
    """Runs one tick of team logic. Any runtime error is caught and logged
    as an idle tick rather than crashing the battle."""
    try:
        decide_fn(friendly, enemies, api)
        return "ok"
    except Exception as e:
        return f"error: {e}"
