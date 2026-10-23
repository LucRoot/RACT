"""ADR-0049 D13 (B-070): the checkpoint a run keeps, read as untrusted data.

The checkpoint lives in the user state directory, never in the workspace,
and is still read as hostile input: the run id is a name, a link is not
read, the size is capped, the schema is closed, the root must be this
repository's, and the plan must match its `plan_hash`. Resetting the step
that was interrupted restores what that step replaced and removes what it
created, byte for byte, and leaves a file the user changed since as it is.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from ract import run_checkpoint as rc
from ract import undo_backup
from ract.manager import Plan, Step

PLAN = Plan(
    assumption="a",
    confidence=0.9,
    steps=[
        Step(
            action="Create util", provider_hint="local", expected_artifact="src/util.py"
        ),
        Step(
            action="Extend util", provider_hint="local", expected_artifact="src/util.py"
        ),
        Step(action="Write notes", provider_hint="local", expected_artifact="notes.md"),
    ],
)


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "state"
    home.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home))


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    return root


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(root: Path, rel: str, data: bytes) -> None:
    """A writer as the executor is one: save first, write, then say so."""
    undo_backup.save_before_replace(root, [rel])
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(data)
    rc.note_written(root, [root / rel])


def _interrupted_run(ws: Path, *, step_2_bytes: bytes = b"step two\r\n\xff") -> None:
    """Step 1 finishes, step 2 writes and is killed before it finishes.

    A kill is simulated by leaving the contexts without finishing step 2;
    nothing at the end of a turn is needed for the checkpoint to be whole.
    """
    checkpoint = rc.RunCheckpoint(ws, "r1", "make util")
    with undo_backup.turn(ws), rc.recording(checkpoint):
        checkpoint.plan_ready(PLAN)
        rc.step_started(1)
        _write(ws, "src/util.py", b"step one\n")
        rc.step_finished(1)
        rc.step_started(2)
        _write(ws, "src/util.py", step_2_bytes)
        _write(ws, "src/new.py", b"created by step two\n")


# ------------------------------------------------------------ when it is written


def test_in_progress_is_recorded_before_the_step_touches_a_file(
    ws: Path, state: None
) -> None:
    (ws / "src" / "a.py").write_bytes(b"old = 1\n")
    checkpoint = rc.RunCheckpoint(ws, "r1", "edit a")
    with undo_backup.turn(ws) as backup, rc.recording(checkpoint):
        checkpoint.plan_ready(PLAN)
        rc.step_started(1)
        on_disk = rc.load(ws, "r1")
        assert on_disk is not None
        assert on_disk["in_progress"] == {
            "n": 1,
            "backup_id": backup.turn_id,
            "worktree": None,
            "files": [],
        }

        undo_backup.save_before_replace(ws, ["src/a.py"])
        # Saved, not yet written: the checkpoint on disk already names it.
        on_disk = rc.load(ws, "r1")
        assert on_disk is not None
        assert on_disk["in_progress"]["files"] == [
            {
                "path": "src/a.py",
                "before": _sha(b"old = 1\n"),
                "after": None,
                "written": False,
            }
        ]
        assert (ws / "src" / "a.py").read_bytes() == b"old = 1\n"


def test_a_finished_step_is_recorded_and_clears_in_progress(
    ws: Path, state: None
) -> None:
    checkpoint = rc.RunCheckpoint(ws, "r1", "make util")
    with undo_backup.turn(ws), rc.recording(checkpoint):
        checkpoint.plan_ready(PLAN)
        rc.step_started(1)
        _write(ws, "src/util.py", b"x\n")
        rc.step_finished(1)
    on_disk = rc.load(ws, "r1")
    assert on_disk is not None
    assert on_disk["finished"] == [1]
    assert on_disk["in_progress"] is None
    assert on_disk["plan_hash"] == rc.plan_hash(PLAN)


def test_a_deferred_finish_is_not_recorded_until_the_caller_says_so(
    ws: Path, state: None
) -> None:
    """The worktree path: the executor finishing in the step's worktree is
    not the step finishing; its changes reach the user's files later."""
    checkpoint = rc.RunCheckpoint(ws, "r1", "make util")
    with undo_backup.turn(ws), rc.recording(checkpoint):
        checkpoint.plan_ready(PLAN)
        rc.step_started(1)
        with rc.finish_deferred():
            rc.step_started(1)  # the executor's own start: same step, kept
            rc.step_finished(1)
        on_disk = rc.load(ws, "r1")
        assert on_disk is not None
        assert on_disk["finished"] == []
        assert on_disk["in_progress"]["n"] == 1
        rc.step_finished(1)
    on_disk = rc.load(ws, "r1")
    assert on_disk is not None and on_disk["finished"] == [1]


def test_every_write_is_atomic_and_leaves_no_temporary_file(
    ws: Path, state: None
) -> None:
    _interrupted_run(ws)
    folder = rc.checkpoint_path(ws, "r1").parent
    assert sorted(p.name for p in folder.iterdir()) == ["r1.json"]


def test_the_checkpoint_is_never_under_the_workspace(ws: Path, state: None) -> None:
    _interrupted_run(ws)
    path = rc.checkpoint_path(ws, "r1")
    assert ws.resolve() not in path.resolve().parents
    assert not any(p.suffix == ".json" for p in ws.rglob("*") if "r1" in p.name)


def test_a_completed_run_removes_its_checkpoint(ws: Path, state: None) -> None:
    checkpoint = rc.RunCheckpoint(ws, "r1", "one step")
    one = Plan(assumption="a", confidence=1.0, steps=[PLAN.steps[0]])
    with undo_backup.turn(ws), rc.recording(checkpoint):
        checkpoint.plan_ready(one)
        rc.step_started(1)
        _write(ws, "src/util.py", b"x\n")
        rc.step_finished(1)
    checkpoint.complete()
    assert not rc.checkpoint_path(ws, "r1").exists()


# ------------------------------------------------------------ hostile input


def _valid(ws: Path) -> dict:
    _interrupted_run(ws)
    data = json.loads(rc.checkpoint_path(ws, "r1").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _plant(ws: Path, data: object, run_id: str = "r1") -> None:
    path = rc.checkpoint_path(ws, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_a_truncated_checkpoint_is_refused(ws: Path, state: None) -> None:
    _interrupted_run(ws)
    path = rc.checkpoint_path(ws, "r1")
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) // 2])
    with pytest.raises(rc.CheckpointRefused, match="complete"):
        rc.load(ws, "r1")


def test_an_oversized_checkpoint_is_refused(ws: Path, state: None) -> None:
    data = _valid(ws)
    data["intent"] = "x" * (rc.MAX_CHECKPOINT_BYTES + 1)
    _plant(ws, data)
    with pytest.raises(rc.CheckpointRefused, match="larger"):
        rc.load(ws, "r1")


def test_a_linked_checkpoint_is_refused(ws: Path, state: None, tmp_path: Path) -> None:
    data = _valid(ws)
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(json.dumps(data), encoding="utf-8")
    path = rc.checkpoint_path(ws, "r1")
    path.unlink()
    try:
        os.symlink(elsewhere, path)
    except OSError:
        pytest.skip("symbolic links need a privilege this machine does not grant")
    with pytest.raises(rc.CheckpointRefused, match="link"):
        rc.load(ws, "r1")


def test_a_foreign_checkpoint_is_refused(ws: Path, state: None) -> None:
    data = _valid(ws)
    data["root"] = "C:\\somewhere\\else"
    _plant(ws, data)
    with pytest.raises(rc.CheckpointRefused, match="another repository"):
        rc.load(ws, "r1")


def test_a_checkpoint_for_another_run_is_refused(ws: Path, state: None) -> None:
    data = _valid(ws)
    _plant(ws, data, run_id="r2")
    with pytest.raises(rc.CheckpointRefused, match="another run"):
        rc.load(ws, "r2")


def test_a_plan_hash_mismatch_is_not_trusted(ws: Path, state: None) -> None:
    data = _valid(ws)
    data["plan"]["steps"][1]["action"] = "Delete everything"
    _plant(ws, data)
    with pytest.raises(rc.CheckpointRefused, match="plan_hash"):
        rc.load(ws, "r1")


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda d: d.update(extra=1), id="unknown-key"),
        pytest.param(lambda d: d.pop("finished"), id="missing-key"),
        pytest.param(lambda d: d.update(finished="1"), id="finished-not-a-list"),
        pytest.param(lambda d: d.update(finished=[True]), id="bool-as-step"),
        pytest.param(lambda d: d.update(finished=[9]), id="step-out-of-range"),
        pytest.param(lambda d: d.update(finished=[1, 1]), id="step-twice"),
        pytest.param(lambda d: d.update(schema="ract.checkpoint/2"), id="schema"),
        pytest.param(lambda d: d["in_progress"].update(n=1), id="in-progress-finished"),
        pytest.param(
            lambda d: d["in_progress"].update(backup_id="../.."), id="backup-id"
        ),
        pytest.param(lambda d: d["in_progress"].update(worktree="../x"), id="worktree"),
        pytest.param(
            lambda d: d["in_progress"].update(evil=True), id="in-progress-key"
        ),
        pytest.param(
            lambda d: d["in_progress"]["files"][0].update(before="not-a-hash"),
            id="file-hash",
        ),
        pytest.param(
            lambda d: d["in_progress"]["files"][0].update(written="yes"),
            id="file-written",
        ),
        pytest.param(lambda d: d["plan"]["steps"][0].update(n=2), id="step-number"),
        pytest.param(lambda d: d["plan"].update(steps=[]), id="no-steps"),
        pytest.param(lambda d: d.update(plan_hash=5), id="hash-type"),
    ],
)
def test_a_checkpoint_outside_the_schema_is_refused(
    ws: Path, state: None, change
) -> None:
    data = _valid(ws)
    change(data)
    _plant(ws, data)
    with pytest.raises(rc.CheckpointRefused):
        rc.load(ws, "r1")


@pytest.mark.parametrize("run_id", ["../x", "..", "", ".hidden", "a/b", "C:x", "a\\b"])
def test_a_run_id_that_is_not_a_name_is_refused(
    ws: Path, state: None, run_id: str
) -> None:
    with pytest.raises(rc.CheckpointRefused):
        rc.load(ws, run_id)


def test_no_checkpoint_gives_none(ws: Path, state: None) -> None:
    assert rc.load(ws, "never-ran") is None


# ------------------------------------------------------------ reset on resume


def test_the_interrupted_steps_partial_change_is_undone_byte_for_byte(
    ws: Path, state: None
) -> None:
    _interrupted_run(ws)
    data = rc.load(ws, "r1")
    assert data is not None

    result = rc.reset_in_progress(ws, data)

    # Step 1's version comes back, not the file as it was before the run.
    assert (ws / "src" / "util.py").read_bytes() == b"step one\n"
    assert not (ws / "src" / "new.py").exists()
    assert sorted(result.undone) == ["src/new.py", "src/util.py"]
    assert result.left == []


def test_the_users_edit_to_a_file_the_interrupted_step_touched_survives(
    ws: Path, state: None
) -> None:
    _interrupted_run(ws)
    users = b"the user's own edit\r\n\x00\xfe"
    (ws / "src" / "util.py").write_bytes(users)
    data = rc.load(ws, "r1")
    assert data is not None

    result = rc.reset_in_progress(ws, data)

    assert (ws / "src" / "util.py").read_bytes() == users
    assert [path for path, _ in result.left] == ["src/util.py"]
    assert result.undone == ["src/new.py"]


def test_a_file_saved_but_not_written_is_left_alone(ws: Path, state: None) -> None:
    (ws / "src" / "a.py").write_bytes(b"old\n")
    checkpoint = rc.RunCheckpoint(ws, "r1", "edit a")
    with undo_backup.turn(ws), rc.recording(checkpoint):
        checkpoint.plan_ready(PLAN)
        rc.step_started(1)
        undo_backup.save_before_replace(ws, ["src/a.py"])
    (ws / "src" / "a.py").write_bytes(b"changed by someone\n")
    data = rc.load(ws, "r1")
    assert data is not None

    result = rc.reset_in_progress(ws, data)

    assert (ws / "src" / "a.py").read_bytes() == b"changed by someone\n"
    assert [path for path, _ in result.left] == ["src/a.py"]


@pytest.mark.parametrize(
    "entry", ["../outside.txt", "/etc/passwd", ".git/config", "src/../../x", "C:/x"]
)
def test_a_reset_never_touches_a_path_outside_the_workspace(
    ws: Path, state: None, tmp_path: Path, entry: str
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"keep me\n")
    data = _valid(ws)
    data["in_progress"]["files"].append(
        {"path": entry, "before": None, "after": _sha(b"keep me\n"), "written": True}
    )
    _plant(ws, data)
    loaded = rc.load(ws, "r1")
    assert loaded is not None

    result = rc.reset_in_progress(ws, loaded)

    assert outside.read_bytes() == b"keep me\n"
    assert entry in [path for path, _ in result.left]


def test_a_reset_records_that_nothing_is_in_progress(ws: Path, state: None) -> None:
    _interrupted_run(ws)
    data = rc.load(ws, "r1")
    assert data is not None
    rc.reset_in_progress(ws, data)
    again = rc.load(ws, "r1")
    assert again is not None
    assert again["in_progress"] is None
    assert again["finished"] == [1]


def test_the_notices_name_every_step(ws: Path, state: None) -> None:
    _interrupted_run(ws)
    data = rc.load(ws, "r1")
    assert data is not None
    result = rc.reset_in_progress(ws, data)

    assert rc.resume_notices(data, result) == [
        "step 1 done earlier, not run again",
        "step 2 was interrupted; its partial change was undone; running it again",
        "step 3 next",
    ]


def test_the_stored_plan_comes_back_as_it_was(ws: Path, state: None) -> None:
    data = _valid(ws)
    assert rc.stored_plan(data) == PLAN
