"""Every event kind the source code emits is in the closed ``EventKind``.

``Event.__post_init__`` refuses an unknown kind, and the emit helpers swallow
that error, so an unregistered kind is not a crash: it silently disappears
from the trace. ``tool.invocation.*`` and ``compensator.*`` were lost this way
for several releases (board S-002). This test reads every string literal that
looks like a dotted event kind in ``src/ract`` and is passed to an emit call,
directly or through a conditional expression, and checks it is registered.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ract.trace.events import LEGAL_EVENT_KINDS

SRC = Path(__file__).resolve().parents[2] / "src" / "ract"
EMIT_NAMES = {"emit", "_emit", "emit_event", "_emit_event", "_emit_step_event"}


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _kind_literals(node: ast.AST) -> list[str]:
    """String literals in the first argument, including both arms of a ternary."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _kind_literals(node.body) + _kind_literals(node.orelse)
    return []


def _emitted_kinds() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) not in EMIT_NAMES:
                continue
            if not node.args:
                continue
            for literal in _kind_literals(node.args[0]):
                if (
                    "." in literal
                    and literal.replace(".", "").replace("_", "").isalnum()
                ):
                    found.setdefault(literal, set()).add(
                        path.relative_to(SRC).as_posix()
                    )
    return found


def test_scan_finds_the_known_emitters() -> None:
    kinds = _emitted_kinds()
    assert "tool.invocation.pre" in kinds
    assert "compensator.applied" in kinds  # conditional (ternary) emit
    assert len(kinds) > 30


def test_every_emitted_kind_is_registered() -> None:
    missing = {
        k: sorted(v) for k, v in _emitted_kinds().items() if k not in LEGAL_EVENT_KINDS
    }
    assert missing == {}, (
        f"emitted but not in EventKind (dropped from the trace): {missing}"
    )
