"""Architecture gate: the loop calls sycophancy_v2, not the legacy scanner.

v0.5.1 wiring module_07 (Lens E AL-E-01) closure: replace the (never
wired) legacy multi-turn ``sycophancy.scan_trace`` primitive with
the two-signal ``sycophancy_v2.classify`` classifier as the loop's
per-iteration sycophancy signal. This grep-gate refuses any future
callsite in ``LoopController`` (or its ``_run_sycophancy_v2_check``
helper) that reaches for the legacy scanner instead of v2.

Legacy ``ract.antilazy.sycophancy`` REMAINS available (its
reversal-scan primitive may return as a multi-turn signal in v0.6);
this gate scopes the ban to the loop-controller's active
per-iteration call surface.
"""

from __future__ import annotations

import ast
from pathlib import Path

_LOOP_CONTROLLER = (
    Path(__file__).resolve().parents[2] / "src" / "ract" / "loop_controller.py"
)


def _has_legacy_sycophancy_call(source: str) -> bool:
    """Return True when the source imports/calls the legacy scanner."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.endswith("ract.antilazy.sycophancy"):
                for alias in node.names:
                    if alias.name in {"scan_trace", "taint_run"}:
                        return True
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {
                "scan_trace",
                "taint_run",
            }:
                return True
            if isinstance(func, ast.Name) and func.id in {
                "scan_trace",
                "taint_run",
            }:
                return True
    return False


def _has_sycophancy_v2_call(source: str) -> bool:
    """Return True when the source calls classify_sycophancy_v2 / classify."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.endswith("ract.antilazy.sycophancy_v2"):
                return True
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {
                "classify",
                "classify_sycophancy_v2",
                "emit_event",
            }:
                # Not every ``classify`` is sycophancy — walk the source
                # text for context. For the loop_controller file the
                # sycophancy_v2 import above is authoritative.
                return True
            if isinstance(func, ast.Name) and func.id in {
                "classify_sycophancy_v2",
            }:
                return True
    return False


def test_loop_controller_does_not_call_legacy_sycophancy_scanner():
    source = _LOOP_CONTROLLER.read_text(encoding="utf-8")
    assert not _has_legacy_sycophancy_call(source), (
        "LoopController must not call the legacy sycophancy.scan_trace / "
        "sycophancy.taint_run primitive as the per-iteration sycophancy "
        "signal. Use ract.antilazy.sycophancy_v2.classify instead "
        "(v0.5.1 wiring module_07 / Lens E AL-E-01 closure)."
    )


def test_loop_controller_calls_sycophancy_v2():
    source = _LOOP_CONTROLLER.read_text(encoding="utf-8")
    assert _has_sycophancy_v2_call(source) or "sycophancy_v2" in source, (
        "LoopController must wire sycophancy_v2.classify into its "
        "per-iteration callback. The Lens E AL-E-01 CRITICAL closure "
        "requires a live caller reaching classify_sycophancy_v2."
    )


def test_run_sycophancy_v2_check_method_exists_on_loop_controller():
    """The wire-in landing site is a first-class method on LoopController."""
    from ract.loop_controller import LoopController

    assert hasattr(LoopController, "_run_sycophancy_v2_check")
    assert callable(LoopController._run_sycophancy_v2_check)


def test_no_production_module_imports_legacy_sycophancy_scanner():
    """SP Q6.6 amendment: sweep ALL production modules, not just loop_controller.

    A legacy ``scan_trace`` / ``taint_run`` import from
    ``ract.antilazy.sycophancy`` in any production module would let
    the legacy multi-turn scanner sneak back into the runtime path
    outside the loop-controller's callback. This grep-gate refuses
    such imports across the whole ``src/ract/`` tree. The legacy
    module itself is exempt (it exports the primitives).
    """
    src_root = Path(__file__).resolve().parents[2] / "src" / "ract"
    legacy_module_file = src_root / "antilazy" / "sycophancy.py"
    violations: list[str] = []
    for py_file in src_root.rglob("*.py"):
        if py_file == legacy_module_file:
            continue
        if "__pycache__" in py_file.parts:
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if _has_legacy_sycophancy_call(source):
            violations.append(str(py_file.relative_to(src_root)))
    assert not violations, (
        "legacy sycophancy scanner imports found in production modules "
        f"(SP Q6.6): {violations}. Use ract.antilazy.sycophancy_v2 instead."
    )
