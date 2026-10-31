"""Package 5 (handoff H6): a snapshot failure ends the step as a result, not an escaped exception.

substrate_adapter.run_via_substrate called take_snapshot with no guard; the WorktreeError escaped
the substrate and reached the turn guard (windows_files.md, locked-file case). It must come back as a
failed Rooted value with the snapshot sentence.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ract.executor import substrate_adapter
from ract.executor.worktree import WorktreeError
from ract.manager import Plan, Step


def _harness(project: Path) -> SimpleNamespace:
    executor = SimpleNamespace(
        hold_step_report=False,
        step_number_offset=0,
        release_held_step=lambda *args, **kwargs: None,
    )
    return SimpleNamespace(project_dir=project, executor=executor)


def test_a_snapshot_failure_is_returned_as_a_failed_result(tmp_path, monkeypatch):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)

    def boom(*args, **kwargs):
        raise WorktreeError(
            "could not snapshot the working tree: open src/calc.py: Permission denied"
        )

    monkeypatch.setattr(substrate_adapter, "take_snapshot", boom)
    plan = Plan(
        assumption="write the file",
        confidence=0.9,
        steps=[
            Step(
                action="write the file",
                provider_hint="",
                expected_artifact="src/calc.py",
            )
        ],
    )
    result = substrate_adapter.run_via_substrate(
        _harness(tmp_path), "write the file", plan
    )
    assert not result.is_ok()
    assert "could not snapshot" in result.error


def test_a_folder_that_is_not_a_repository_is_a_failed_result(tmp_path):
    plan = Plan(
        assumption="write the file",
        confidence=0.9,
        steps=[
            Step(action="write the file", provider_hint="", expected_artifact="a.py")
        ],
    )
    result = substrate_adapter.run_via_substrate(
        _harness(tmp_path), "write the file", plan
    )
    assert not result.is_ok()
    assert "not a git repository" in result.error
