"""v0.5.1 spec-completeness module_02 — AST grep-gate: input_max paired.

Closes audit Lens 1A CRITICAL A-1
(``_BUILD/audit_2026-08-21c/lens_1A_budget_system.md`` §CRITICAL-A):
every function-scope invocation site that calls ``refuse_over_ceiling``
MUST ALSO call ``refuse_over_max`` in the same function-scope
(before it, though ordering enforcement is separate: this test just
enforces PAIRING).

Rationale: the ``input_max`` boundary is the master spec's HARD
REJECTION line. Any caller that goes through the ceiling gate without
the max gate is silently accepting invocations between input_max and
hard_ceiling — the exact loophole this module closes. The test refuses
commits that reintroduce that loophole.

Scope: every ``.py`` file under ``src/ract/`` that calls
``refuse_over_ceiling(`` in a function scope must call
``refuse_over_max(`` in the same function scope. Definition sites
(``src/ract/memory/functions/provider_adapter.py``) and re-export
sites (``src/ract/memory/functions/__init__.py``) are exempted by
name.
"""

from __future__ import annotations

import ast
from pathlib import Path


# The definition module ships both functions and re-exports them; it is
# the site that DEFINES the wiring, not a caller.
_DEFINITION_FILES: frozenset[str] = frozenset(
    {
        "ract/memory/functions/provider_adapter.py",
    }
)

# Re-export namespaces (import both but don't call them at function
# scope).
_REEXPORT_FILES: frozenset[str] = frozenset(
    {
        "ract/memory/functions/__init__.py",
    }
)


def _iter_py_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).as_posix()
        if "__pycache__" in rel:
            continue
        yield rel, path


def _call_name(node: ast.Call) -> str | None:
    """Return the bare callable name for an ast.Call, or None.

    Handles both ``refuse_over_ceiling(...)`` and
    ``module.refuse_over_ceiling(...)`` shapes.
    """
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _walk_function_bodies(tree: ast.AST):
    """Yield every function/async-function body in ``tree`` (nested included)."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _function_calls(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return the set of bare call-names in ``fn``'s body."""
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name is not None:
                names.add(name)
    return names


def test_every_refuse_over_ceiling_caller_also_calls_refuse_over_max() -> None:
    """Grep-gate refuses commits that add a ceiling check without input_max.

    The AST walk is scoped per-function so a large file can have several
    unrelated callers; each must be individually paired.
    """
    src_root = Path(__file__).resolve().parents[2] / "src" / "ract"
    violations: list[str] = []

    for rel, path in _iter_py_files(src_root):
        if rel in _DEFINITION_FILES or rel in _REEXPORT_FILES:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            # A syntax error in a non-target file is a separate concern.
            continue
        for fn in _walk_function_bodies(tree):
            calls = _function_calls(fn)
            if "refuse_over_ceiling" not in calls:
                continue
            if "refuse_over_max" not in calls:
                violations.append(
                    f"{rel}::{fn.name} calls refuse_over_ceiling "
                    f"without paired refuse_over_max (line {fn.lineno})"
                )

    assert not violations, (
        "v0.5.1 module_02 grep-gate: every function scope that calls "
        "refuse_over_ceiling must also call refuse_over_max. "
        "Violations:\n" + "\n".join(violations)
    )


def test_all_four_shipped_functions_are_paired() -> None:
    """Positive-existence check: the 4 shipped memory functions ARE paired.

    Complements the negative check above with an explicit assertion
    that intake/research/plan/edit each carry both calls today. If a
    future refactor moves the calls into a helper this test needs
    updating — the pair rule stays; the location may move.
    """
    src_root = Path(__file__).resolve().parents[2] / "src" / "ract"
    expected = {
        "intake": "ract/memory/functions/intake.py",
        "research": "ract/memory/functions/research.py",
        "plan": "ract/memory/functions/plan.py",
        "edit": "ract/memory/functions/edit.py",
    }
    for func_name, rel in expected.items():
        path = src_root.parent / rel
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        paired_functions: list[str] = []
        for fn in _walk_function_bodies(tree):
            calls = _function_calls(fn)
            if "refuse_over_max" in calls and "refuse_over_ceiling" in calls:
                paired_functions.append(fn.name)
        assert func_name in paired_functions, (
            f"{rel}: expected a paired refuse_over_max/refuse_over_ceiling "
            f"in a function named {func_name!r}; paired functions found: "
            f"{paired_functions}"
        )


def test_refuse_over_max_defined_in_provider_adapter() -> None:
    """Anchor the definition site so the grep-gate exemption is honest."""
    src_root = Path(__file__).resolve().parents[2] / "src" / "ract"
    provider_adapter = src_root / "memory" / "functions" / "provider_adapter.py"
    tree = ast.parse(provider_adapter.read_text(encoding="utf-8", errors="replace"))
    fn_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "refuse_over_max" in fn_names
    assert "refuse_over_ceiling" in fn_names
    assert "seat_state_section" in fn_names


# RACT 0.5.1
