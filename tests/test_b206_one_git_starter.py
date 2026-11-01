"""B-206: RACT starts git one way, and an exemption names a file that still needs it.

``run_git`` (``git_run.py``) applies G-239's whole hardening; the git tools
(``tools/git_tools.py``) have their own capped runner with the same argv. No
other source file builds a git argv for ``subprocess`` itself. An entry in the
tool gate's exempt sites is permission to call ``subprocess`` directly, so a
file that no longer does loses its entry.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ract.executor.tool_gate import exempt_sites

SRC = Path(__file__).resolve().parents[1] / "src" / "ract"
GIT_STARTERS = {"git_run.py", "tools/git_tools.py"}
CALLS = {"run", "Popen", "call", "check_output", "check_call"}


def _subprocess_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"subprocess", "_sp"}
        and node.func.attr in CALLS
    ]


def _starts_git(call: ast.Call) -> bool:
    if not call.args or not isinstance(call.args[0], (ast.List, ast.Tuple)):
        return False
    elts = call.args[0].elts
    if not elts:
        return False
    first = elts[0]
    if isinstance(first, ast.Constant) and first.value == "git":
        return True
    return (
        isinstance(first, ast.Call)
        and isinstance(first.func, ast.Attribute)
        and first.func.attr == "git"
        and isinstance(first.func.value, ast.Name)
        and first.func.value.id == "programs"
    )


def _modules():
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        yield rel, ast.parse(path.read_text(encoding="utf-8"))


def test_no_file_but_the_git_starters_builds_a_git_argv_for_subprocess() -> None:
    found = [
        f"{rel}:{call.lineno}"
        for rel, tree in _modules()
        if rel not in GIT_STARTERS
        for call in _subprocess_calls(tree)
        if _starts_git(call)
    ]
    assert not found, "start git with ract.git_run.run_git: " + ", ".join(found)


def test_every_exempt_site_still_calls_subprocess() -> None:
    trees = dict(_modules())
    stale = [
        rel
        for rel in exempt_sites()
        if rel.endswith(".py") and rel in trees and not _subprocess_calls(trees[rel])
    ]
    assert not stale, "exempt sites with no subprocess call left: " + ", ".join(stale)
