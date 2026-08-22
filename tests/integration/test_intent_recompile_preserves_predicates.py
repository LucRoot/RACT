"""``recompile_intent`` must not silently strip predicates (Lens D D4).

Lens D D4 identified that ``_recompile_intent_locked`` called
``IntentCompiler.compile(intent_text, WorkspaceSnapshot())``, passing an
EMPTY workspace snapshot. ``_discover_test_files`` returned zero test
files, so the fresh suite carried zero required predicates. The
loop's ``check_t1`` (required-predicate coverage gate) then always
passed because there was nothing to fail, silently defeating T1 whenever
an operator legitimately used ``ract intent recompile``.

Wiring module_02 fix: the recompile scans the workspace root (parent
of ``.ract``) for source + tests, and a second-line defence preserves
the prior suite's predicates when the fresh compile yields a smaller
required set.

These regressions exercise BOTH paths:
1. A non-empty workspace populates the fresh suite with real predicates.
2. When the workspace root cannot be located, the prior suite's
   predicates are preserved verbatim rather than dropped.

Reference:
- ``_BUILD/audit_2026-08-21/lens_D_rootknot_signatures.md`` D4.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_02.md``.
"""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest

from ract.core.intent_recompile import recompile_intent


@pytest.fixture
def workspace_tree(tmp_path: Path) -> dict[str, Path]:
    """Populate a workspace with a source module, a test file, and a run dir."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "widget.py").write_text(
        "def add(x, y):\n    return x + y\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_widget.py").write_text(
        "def test_add():\n    from src.widget import add\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    ract_dir = tmp_path / ".ract"
    ract_dir.mkdir()
    (ract_dir / "operator.key").write_bytes(secrets.token_bytes(64))
    runs_root = ract_dir / "runs"
    runs_root.mkdir()
    run_dir = runs_root / "run-d4-fixture"
    run_dir.mkdir()

    # Seed prior suite.json via a full compile against the real snapshot
    # so the prior suite carries real predicates (this is what the loop
    # would have written on the initial compile).
    from ract.core.compile import IntentCompiler
    from ract.core.loop import WorkspaceSnapshot

    files = {
        "src/widget.py": (tmp_path / "src" / "widget.py").read_text(),
        "tests/test_widget.py": (tmp_path / "tests" / "test_widget.py").read_text(),
    }
    prior_ws = WorkspaceSnapshot(files=files, timestamp=0.0)
    compiler = IntentCompiler()
    prior = compiler.compile("original intent", prior_ws)
    prior_suite = prior.visible if hasattr(prior, "visible") else prior  # type: ignore[union-attr]
    (run_dir / "suite.json").write_text(prior_suite.to_json(), encoding="utf-8")

    return {"tmp": tmp_path, "ract_dir": ract_dir, "run_dir": run_dir}


def test_recompile_with_scanned_workspace_yields_predicates(
    workspace_tree: dict[str, Path],
) -> None:
    """Auto-scan (no ``workspace`` kwarg) walks the ``.ract`` ancestor."""
    result = recompile_intent(
        run_dir=workspace_tree["run_dir"],
        intent_text="refined intent after auto-scan",
        ract_dir=workspace_tree["ract_dir"],
    )
    # The fresh suite must carry at least one required predicate --
    # the test file the auto-scan found under ``tests/``.
    required = [p for p in result.new_suite.predicates if getattr(p, "required", False)]
    assert len(required) > 0, (
        "recompile produced zero required predicates -- Lens D D4 regression "
        "(empty WorkspaceSnapshot fallthrough)."
    )


def test_recompile_with_explicit_workspace_preserves_predicates(
    workspace_tree: dict[str, Path],
) -> None:
    """A caller-supplied snapshot is used verbatim; predicates non-empty."""
    from ract.core.loop import WorkspaceSnapshot

    ws = WorkspaceSnapshot(
        files={
            "tests/test_widget.py": (
                workspace_tree["tmp"] / "tests" / "test_widget.py"
            ).read_text(),
        },
        timestamp=0.0,
    )
    result = recompile_intent(
        run_dir=workspace_tree["run_dir"],
        intent_text="refined intent with explicit workspace",
        ract_dir=workspace_tree["ract_dir"],
        workspace=ws,
    )
    required = [p for p in result.new_suite.predicates if getattr(p, "required", False)]
    assert len(required) > 0
    # New prompt_digest fires as always.
    assert result.new_suite.prompt_digest is not None


def test_recompile_falls_back_to_prev_predicates_when_scan_yields_less(
    workspace_tree: dict[str, Path],
) -> None:
    """Empty workspace kwarg triggers the preserve-prev-suite defence.

    The prior suite has at least one required predicate (the ``tests/``
    file). A recompile with an empty snapshot would normally strip
    every predicate; the D4 preserve-defence keeps them.
    """
    from ract.core.loop import WorkspaceSnapshot

    result = recompile_intent(
        run_dir=workspace_tree["run_dir"],
        intent_text="refined intent under starved snapshot",
        ract_dir=workspace_tree["ract_dir"],
        workspace=WorkspaceSnapshot(),
    )
    required = [p for p in result.new_suite.predicates if getattr(p, "required", False)]
    assert len(required) > 0, (
        "recompile with empty workspace should PRESERVE the prior suite's "
        "predicates rather than drop them -- Lens D D4 second-line defence."
    )
