"""Grep-gate: SubstrateLoop's step-spawn surface routes through
``ract.executor.process_group.spawn``, and rollback paths route
through ``ract.executor.process_group.kill_tree``.

v0.5.1 wiring module_05 (Lens C C-03) closure. The Lens C audit
established that ``process_group.spawn`` / ``kill_tree`` had zero
production callers: they existed only as isolated primitives whose
sole callers were their own tests. This test locks the wire-in --
:meth:`ract.executor.loop.SubstrateLoop.spawn_step_subprocess`
MUST reference :func:`process_group.spawn`, and
:meth:`SubstrateLoop._reap_active_processes` MUST reference
:func:`process_group.kill_tree`.

The test is deliberately structural (AST + attribute presence)
rather than behavioral -- behavioral coverage lives in the unit /
integration test batch below. This one asserts the WIRE EXISTS,
so a future refactor that silently swaps ``spawn`` for a bare
``subprocess.Popen`` (regressing the Lens C fix) fails here.

Reference:
- ``_BUILD/audit_2026-08-21/lens_C_substrate_sandbox.md`` C-03.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_05.md``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ract.executor import loop as loop_mod
from ract.executor import process_group as pg_mod
from ract.executor.loop import SubstrateLoop


_LOOP_PATH = Path(loop_mod.__file__)


def _read_loop_source() -> str:
    return _LOOP_PATH.read_text(encoding="utf-8")


def _method_source(method_name: str) -> str:
    """Return the source text of ``SubstrateLoop.<method_name>``.

    AST-based extraction so docstring mentions in other methods
    cannot masquerade as call references.
    """
    tree = ast.parse(_read_loop_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SubstrateLoop":
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == method_name
                ):
                    return ast.unparse(item)
    raise AssertionError(
        f"SubstrateLoop.{method_name} not found -- Lens C C-03 wire-in reverted?"
    )


# ---------------------------------------------------------------------------
# spawn wiring
# ---------------------------------------------------------------------------


def test_substrate_loop_exposes_spawn_step_subprocess_method() -> None:
    """The wire-in surface must exist on the class."""
    assert hasattr(SubstrateLoop, "spawn_step_subprocess"), (
        "SubstrateLoop.spawn_step_subprocess method missing -- module_05 "
        "wire-in for Lens C C-03 (process-group tree-kill) has not "
        "shipped."
    )
    assert callable(SubstrateLoop.spawn_step_subprocess), (
        "SubstrateLoop.spawn_step_subprocess is not callable."
    )


def test_spawn_step_subprocess_calls_process_group_spawn() -> None:
    """The spawn wire-in must delegate to ``process_group.spawn``."""
    src = _method_source("spawn_step_subprocess")
    assert "spawn(" in src, (
        "SubstrateLoop.spawn_step_subprocess must call "
        "``process_group.spawn(...)`` -- Lens C C-03 wire-in "
        "regressed if this fails."
    )
    # And the returned handle must be tracked so rollback can reap it.
    assert "_active_process_handles" in src, (
        "spawn_step_subprocess must append its handle to "
        "``self._active_process_handles`` so the reaper can find it."
    )


def test_spawn_step_subprocess_consumes_current_sandbox_env() -> None:
    """module_04 SP Q5 defer closure -- Popen(env=) consumes the
    sandbox backend's filtered env when the caller does not override.
    """
    src = _method_source("spawn_step_subprocess")
    assert "_current_sandbox_env" in src, (
        "spawn_step_subprocess must read ``self._current_sandbox_env`` "
        "so module_04's ``build_sandbox_env`` output reaches the "
        "step_runner's subprocess env (module_04 Q5 defer)."
    )


# ---------------------------------------------------------------------------
# reap wiring
# ---------------------------------------------------------------------------


def test_substrate_loop_exposes_reap_active_processes_method() -> None:
    assert hasattr(SubstrateLoop, "_reap_active_processes"), (
        "SubstrateLoop._reap_active_processes method missing -- rollback "
        "cannot reap process trees."
    )


def test_reap_active_processes_calls_process_group_kill_tree() -> None:
    """Reap wire must invoke ``process_group.kill_tree`` per handle."""
    src = _method_source("_reap_active_processes")
    assert "kill_tree(" in src, (
        "_reap_active_processes must call ``process_group.kill_tree(...)`` "
        "per handle -- otherwise descendants leak past rollback (Lens C "
        "C-03 regression)."
    )
    # And the list must clear after reap (else double-kill on next call).
    assert "_active_process_handles" in src, (
        "_reap_active_processes must consume + clear the handle list."
    )


# ---------------------------------------------------------------------------
# dispose wire-in
# ---------------------------------------------------------------------------


def test_dispose_unsuccessful_reaps_active_processes() -> None:
    """dispose(success=False) MUST reap active handles before drain."""
    src = _method_source("dispose")
    # The reap call must appear in the dispose method (either in the
    # unsuccessful branch or before drain -- both closure the same
    # invariant).
    assert "_reap_active_processes(" in src, (
        "SubstrateLoop.dispose(success=False) must call "
        "self._reap_active_processes(...) so a rollback via disposal "
        "reaps every descendant tree BEFORE compensator drain runs. "
        "Otherwise a child holding a worktree file handle can block "
        "the compensator's git reset (Lens C C-03 closure)."
    )


def test_run_step_reaps_on_uncaught_exception() -> None:
    """An uncaught exception in the step_runner MUST reap the tree."""
    src = _method_source("run_step")
    assert "_reap_active_processes(" in src, (
        "SubstrateLoop.run_step must reap the tree in an except block "
        "so an unexpected step_runner exception cannot leak processes "
        "past the step boundary."
    )


# ---------------------------------------------------------------------------
# process_group primitives -- imports live-check
# ---------------------------------------------------------------------------


def test_process_group_primitives_exported() -> None:
    assert hasattr(pg_mod, "spawn")
    assert hasattr(pg_mod, "kill_tree")
    assert hasattr(pg_mod, "ProcessGroupHandle")


def test_loop_module_imports_process_group_primitives() -> None:
    """The loop module must import from process_group at module load."""
    src = _read_loop_source()
    assert "from ract.executor.process_group import" in src, (
        "src/ract/executor/loop.py must import the process_group "
        "primitives at module load so the wire-in is not lazy."
    )
    for symbol in ("spawn", "kill_tree", "ProcessGroupHandle"):
        assert symbol in src, (
            f"loop.py must reference ``{symbol}`` from process_group."
        )


# RACT 0.5.1
