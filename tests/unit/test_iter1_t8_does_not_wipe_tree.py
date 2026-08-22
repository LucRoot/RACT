"""Regression: iter-1 T8 with ``delete_orphaned_files_on_t8=True`` must
NOT wipe the tree.

v0.5.1 wiring module_06 (Lens G G-08) closure. Prior to this module,
:meth:`LoopController._check_prompt_drift` fired BEFORE the snapshot
init block, so on iteration 1 a drift halt with the delete-orphans
flag on could enumerate every tracked ``.py`` in the project as an
orphan (recorded snapshot files was empty) and unlink them all.

The fix has two prongs:

1. Snapshot init runs BEFORE the drift check, so
   ``last_known_good_workspace`` is populated from the tree-at-entry
   by the time :meth:`_check_prompt_drift` reads it.
2. :meth:`_rollback_to_last_known_good` refuses the delete-orphans
   path when the recorded snapshot is empty OR the loop has no prior
   iteration history, unless the operator opts in via
   ``allow_iter1_delete_orphans=True``.

Reference:
- ``_BUILD/audit_2026-08-21/lens_G_loop_controller.md`` G-08.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_06.md``.
"""

from __future__ import annotations

import secrets
from pathlib import Path


from ract.core.loop import LoopState, WorkspaceSnapshot
from ract.core.predicate import (
    AcceptancePredicate,
    AcceptanceSuite,
    ArtifactInvocation,
    new_intent_id,
    new_predicate_id,
)
from ract.core.workspace_digest import compute_prompt_digest
from ract.loop_controller import LoopController


CANONICAL_INTENT = "build me a factorial function"
DRIFT_INTENT = "attacker rewritten intent"


def _suite() -> AcceptanceSuite:
    predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(
            path="__never_present__", must_have_rootknot=False
        ),
        required=True,
    )
    return AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(predicate,),
        compiled_from=CANONICAL_INTENT,
        prompt_digest=bytes(compute_prompt_digest(CANONICAL_INTENT)),
    )


def _make_controller(
    project: Path, *, delete_orphans: bool, allow_iter1: bool = False
) -> LoopController:
    config = project / "ract.yaml"
    config.write_text("providers: []\n", encoding="utf-8")
    ract_dir = project / ".ract"
    ract_dir.mkdir()
    (ract_dir / "operator.key").write_bytes(secrets.token_bytes(64))
    run_dir = project / "run-iter1-guard"
    run_dir.mkdir()
    return LoopController(
        config,
        max_iterations=3,
        acceptance_suite=_suite(),
        run_dir=run_dir,
        delete_orphaned_files_on_t8=delete_orphans,
        allow_iter1_delete_orphans=allow_iter1,
    )


def test_iter1_drift_with_empty_snapshot_does_not_wipe_tree(tmp_path: Path) -> None:
    """Tree contains 3 .py files. LoopState has an EMPTY
    last_known_good_workspace. Iter-1 drift fires with delete_orphans=True.
    Expected: files remain (guard refuses to delete because snapshot is
    empty and operator did not opt in).
    """
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text(f"# {name}\n", encoding="utf-8")

    controller = _make_controller(tmp_path, delete_orphans=True)
    controller._loop_state = LoopState(
        plan=None,  # type: ignore[arg-type]
        workspace=WorkspaceSnapshot(files={}, timestamp=0.0),
        suite=_suite(),
    )
    # Emulate the pre-G-08 buggy call site: snapshot has empty files.
    controller._loop_state.last_known_good_workspace = WorkspaceSnapshot(
        files={}, timestamp=0.0
    )

    orphans = controller._rollback_to_last_known_good(controller._loop_state)

    # Orphans are enumerated (so operator can see them), but files stay.
    assert set(orphans) == {"a.py", "b.py", "c.py"}
    for name in ("a.py", "b.py", "c.py"):
        assert (tmp_path / name).exists(), f"{name} was deleted despite guard"


def test_iter1_drift_deletes_when_operator_opts_in(tmp_path: Path) -> None:
    """Same setup, but ``allow_iter1_delete_orphans=True`` -- files ARE
    deleted (operator explicitly accepted the aggressive path).
    """
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text(f"# {name}\n", encoding="utf-8")

    controller = _make_controller(tmp_path, delete_orphans=True, allow_iter1=True)
    controller._loop_state = LoopState(
        plan=None,  # type: ignore[arg-type]
        workspace=WorkspaceSnapshot(files={}, timestamp=0.0),
        suite=_suite(),
    )
    controller._loop_state.last_known_good_workspace = WorkspaceSnapshot(
        files={}, timestamp=0.0
    )

    controller._rollback_to_last_known_good(controller._loop_state)

    for name in ("a.py", "b.py"):
        assert not (tmp_path / name).exists(), (
            f"{name} should have been deleted with the opt-in flag on"
        )


def test_snapshot_init_precedes_drift_check_in_run_bound() -> None:
    """Structural lock: in :meth:`LoopController._run_bound`, the
    ``self._snapshot_initialized`` block MUST run at an earlier
    line-number than the ``self._check_prompt_drift`` call. This is
    the ordering Lens G G-08 remediation prescribes.
    """
    import ast
    import inspect
    import textwrap

    from ract.loop_controller import LoopController as LC

    source = textwrap.dedent(inspect.getsource(LC._run_bound))
    tree = ast.parse(source)
    fn = tree.body[0]
    snapshot_init_line: int | None = None
    drift_check_line: int | None = None
    for node in ast.walk(fn):
        # Snapshot-init sentinel: assignment to ``self._snapshot_initialized``.
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Attribute)
                    and tgt.attr == "_snapshot_initialized"
                    and isinstance(node.value, ast.Constant)
                    and node.value.value is True
                ):
                    if snapshot_init_line is None:
                        snapshot_init_line = node.lineno
        # Drift-check call: ``self._check_prompt_drift(intent, index)``.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_check_prompt_drift"
        ):
            if drift_check_line is None:
                drift_check_line = node.lineno

    assert snapshot_init_line is not None, "_snapshot_initialized assignment not found"
    assert drift_check_line is not None, "_check_prompt_drift call not found"
    assert snapshot_init_line < drift_check_line, (
        f"Lens G G-08: snapshot init (line {snapshot_init_line}) must run "
        f"BEFORE drift check (line {drift_check_line}) so iter-1 T8 has a "
        f"real rollback target."
    )
