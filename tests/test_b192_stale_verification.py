"""B-192: a passing run followed by a later write is `stale`, never `verified`.

``note_change()`` was never called, so the verifier could not produce ``stale``
(the S7 promise). The turn now counts every write and each run keeps the count
it saw; the record is replayed in that order.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ract import turn_context
from ract.session_turn import verification_record


@dataclass(frozen=True)
class _Run:
    argv: tuple[str, ...] = ("python", "-m", "pytest")
    exit_code: int | None = 0
    killed_by: str | None = None
    duration_ms: int = 5
    runner: str = "process"


def _bind() -> tuple[list[str], list[object]]:
    written: list[str] = []
    runs: list[object] = []
    turn_context.bind(None, written=written, runs=runs)
    return written, runs


def _write(root: Path, name: str, text: str) -> None:
    (root / name).write_text(text, encoding="utf-8")
    turn_context.record_written(root, [name])


def test_a_write_after_a_passing_run_makes_the_turn_stale(tmp_path: Path) -> None:
    _, runs = _bind()
    _write(tmp_path, "a.py", "x = 1\n")
    turn_context.record_run("tests", _Run())
    _write(tmp_path, "a.py", "x = 2\n")  # changed again after the run
    seen = [changes for _kind, _result, changes in runs]  # type: ignore[misc]
    results = [result for _kind, result, _changes in runs]  # type: ignore[misc]
    record = verification_record(results, seen, turn_context.changes_made())
    assert record.result().status == "stale"


def test_a_passing_run_after_the_last_write_is_verified(tmp_path: Path) -> None:
    _, runs = _bind()
    _write(tmp_path, "a.py", "x = 1\n")
    _write(tmp_path, "b.py", "y = 1\n")
    turn_context.record_run("tests", _Run())
    seen = [changes for _kind, _result, changes in runs]  # type: ignore[misc]
    results = [result for _kind, result, _changes in runs]  # type: ignore[misc]
    record = verification_record(results, seen, turn_context.changes_made())
    assert record.result().status == "verified"


def test_a_second_write_to_the_same_file_counts_again(tmp_path: Path) -> None:
    written, _ = _bind()
    _write(tmp_path, "a.py", "x = 1\n")
    _write(tmp_path, "a.py", "x = 2\n")
    assert written == ["a.py"]  # the changed list names the file once
    assert turn_context.changes_made() == 2  # but both writes count


def test_the_same_content_in_another_tree_is_no_new_change(tmp_path: Path) -> None:
    # A step's worktree writes the file, then the apply brings the same bytes
    # (with other line endings) to the operator's tree: one change, not two.
    _bind()
    work, project = tmp_path / "work", tmp_path / "project"
    work.mkdir()
    project.mkdir()
    (work / "a.py").write_bytes(b"x = 2\n")
    turn_context.record_written(work, ["a.py"])
    (project / "a.py").write_bytes(b"x = 2\r\n")
    turn_context.record_written(project, ["a.py"])
    assert turn_context.changes_made() == 1


def test_a_provenance_sidecar_is_no_change(tmp_path: Path) -> None:
    _bind()
    _write(tmp_path, ".a.py.rootknot.json", "{}")
    assert turn_context.changes_made() == 0


def test_a_move_and_a_delete_are_changes() -> None:
    _bind()
    turn_context.note_changed("a.py", b"x\n")
    turn_context.note_changed("a.py", None)
    turn_context.note_changed("b.py", b"x\n")
    assert turn_context.changes_made() == 3


def test_a_failing_run_after_the_last_write_is_failed(tmp_path: Path) -> None:
    _, runs = _bind()
    turn_context.record_written(tmp_path, ["a.py"])
    turn_context.record_run("tests", _Run(exit_code=1))
    seen = [changes for _kind, _result, changes in runs]  # type: ignore[misc]
    results = [result for _kind, result, _changes in runs]  # type: ignore[misc]
    assert verification_record(results, seen, 1).result().status == "failed"


def test_no_run_is_not_run_and_a_fake_run_never_counts() -> None:
    assert verification_record([], [], 3).result().status == "not-run"
    record = verification_record([_Run(runner="fake")], [0], 0)
    assert record.result().status == "not-run"


def test_the_named_test_run_after_the_steps_sees_every_step_write(
    tmp_path: Path,
) -> None:
    # A named test (J4) runs after the steps: it saw all their writes.
    _bind()
    turn_context.record_written(tmp_path, ["a.py"])
    turn_context.record_written(tmp_path, ["b.py"])
    after_steps = turn_context.changes_made()
    record = verification_record([_Run()], [after_steps], after_steps)
    assert record.result().status == "verified"
