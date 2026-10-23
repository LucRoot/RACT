"""ADR-0049 D13 (B-070): the places a run's checkpoint learns what happened.

The executor names a step before it touches a file and records it finished
when the harness says `done`; a finished step of a resumed run is not run
again. Each writer into the user's files (the executor, the diff applier,
the worktree apply) says when it has written. Found on the way: the direct
path never recorded a file it created, so `/undo` left it in place.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from ract import run_checkpoint as rc
from ract import undo_backup
from ract.diff_applier import DiffApplier
from ract.executor import Executor
from ract.executor.worktree import apply_commit_to_working_tree
from ract.manager import Plan, Step
from ract.rooted import Rooted
from tests.test_executor import FakeAdapter, FakeRouter


@pytest.fixture(autouse=True)
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "state"
    home.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home))


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


TWO = Plan(
    assumption="a",
    confidence=0.9,
    steps=[
        Step(action="greet", provider_hint="mock", expected_artifact="greeting.txt"),
        Step(action="part", provider_hint="mock", expected_artifact="farewell.txt"),
    ],
)


class CountingAdapter(FakeAdapter):
    """Counts calls and records the checkpoint as it stands at each call."""

    def __init__(self, ws: Path, contents: list[str]) -> None:
        super().__init__("mock")
        self.ws = ws
        self.contents = contents
        self.calls = 0
        self.in_progress_seen: list[Any] = []

    def complete(self, messages, **kwargs) -> Rooted[dict[str, Any]]:  # type: ignore[override]
        on_disk = rc.load(self.ws, "r1")
        self.in_progress_seen.append(on_disk["in_progress"] if on_disk else None)
        content = self.contents[self.calls]
        self.calls += 1
        return Rooted(
            value={"choices": [{"message": {"content": content}}]},
            assumption="fake adapter responds",
            confidence=1.0,
        )


def _bound(ws: Path, state: dict[str, Any] | None = None) -> rc.RunCheckpoint:
    checkpoint = rc.RunCheckpoint(ws, "r1", "greet and part", state=state)
    return checkpoint


# ------------------------------------------------------------ FOUND


def test_a_file_the_direct_path_creates_is_recorded_so_undo_removes_it(
    ws: Path,
) -> None:
    executor = Executor(FakeRouter(FakeAdapter("mock", "hello\n")), project_dir=ws)
    plan = Plan(assumption="a", confidence=0.9, steps=[TWO.steps[0]])

    with undo_backup.turn(ws) as backup:
        assert executor.execute(intent="greet", plan=plan).is_ok()

    assert backup.created == ["greeting.txt"]
    result = undo_backup.undo(ws)
    assert result.removed == ["greeting.txt"]
    assert not (ws / "greeting.txt").exists()


# ------------------------------------------------------------ executor


def test_the_executor_names_the_step_before_it_writes_and_finishes_it(
    ws: Path,
) -> None:
    adapter = CountingAdapter(ws, ["hello\n", "goodbye, and thanks for the fish\n"])
    executor = Executor(FakeRouter(adapter), project_dir=ws)
    checkpoint = _bound(ws)

    with undo_backup.turn(ws), rc.recording(checkpoint):
        checkpoint.plan_ready(TWO)
        assert executor.execute(intent="greet and part", plan=TWO).is_ok()

    # At each model call the step was already recorded, with no file yet.
    assert [p["n"] for p in adapter.in_progress_seen] == [1, 2]
    assert [p["files"] for p in adapter.in_progress_seen] == [[], []]
    on_disk = rc.load(ws, "r1")
    assert on_disk is not None
    assert on_disk["finished"] == [1, 2]
    assert on_disk["in_progress"] is None


def test_a_finished_step_is_not_run_again(ws: Path) -> None:
    first = _bound(ws)
    with undo_backup.turn(ws), rc.recording(first):
        first.plan_ready(TWO)
        rc.step_started(1)
        rc.step_finished(1)
    state = rc.load(ws, "r1")
    assert state is not None

    adapter = CountingAdapter(ws, ["goodbye, and thanks for the fish\n"])
    executor = Executor(FakeRouter(adapter), project_dir=ws)
    resumed = _bound(ws, state=state)
    with undo_backup.turn(ws), rc.recording(resumed):
        resumed.plan_ready(TWO)
        assert executor.execute(intent="greet and part", plan=TWO).is_ok()

    assert adapter.calls == 1
    assert not (ws / "greeting.txt").exists()
    assert (ws / "farewell.txt").is_file()


def test_a_step_that_fails_stays_in_progress_with_what_it_wrote(ws: Path) -> None:
    (ws / "greeting.txt").write_text("old\n", encoding="utf-8")

    class Failing(FakeAdapter):
        def complete(self, messages, **kwargs):  # type: ignore[override]
            return Rooted(value=None, assumption="down", confidence=0.0, error="boom")

    executor = Executor(FakeRouter(Failing("mock")), project_dir=ws)
    checkpoint = _bound(ws)
    with undo_backup.turn(ws), rc.recording(checkpoint):
        checkpoint.plan_ready(TWO)
        assert not executor.execute(intent="greet and part", plan=TWO).is_ok()

    on_disk = rc.load(ws, "r1")
    assert on_disk is not None
    assert on_disk["finished"] == []
    assert on_disk["in_progress"]["n"] == 1


# ------------------------------------------------------------ writers


def _started(ws: Path) -> rc.RunCheckpoint:
    checkpoint = _bound(ws)
    checkpoint.plan_ready(TWO)
    return checkpoint


def test_the_executor_write_is_recorded_after_it_happens(ws: Path) -> None:
    executor = Executor(FakeRouter(FakeAdapter("mock", "hello\n")), project_dir=ws)
    checkpoint = _started(ws)
    with undo_backup.turn(ws), rc.recording(checkpoint):
        rc.step_started(1)
        # Returns whether provenance was recorded; none is configured here.
        executor._write_artifact("greeting.txt", "hello\n")
        on_disk = rc.load(ws, "r1")

    assert on_disk is not None
    [entry] = on_disk["in_progress"]["files"]
    assert entry["path"] == "greeting.txt"
    assert entry["before"] is None
    assert entry["written"] is True
    assert entry["after"] == rc._sha256(ws / "greeting.txt")


def test_the_diff_applier_write_is_recorded(ws: Path) -> None:
    (ws / "foo.py").write_text("line1\nline2\n", encoding="utf-8")
    diff = "diff --git a/foo.py b/foo.py\n@@ -1,2 +1,2 @@\n line1\n-line2\n+line2b\n"
    checkpoint = _started(ws)
    with undo_backup.turn(ws), rc.recording(checkpoint):
        rc.step_started(1)
        [result] = DiffApplier(ws).apply_diff(diff)
        assert result.applied
        on_disk = rc.load(ws, "r1")

    assert on_disk is not None
    [entry] = on_disk["in_progress"]["files"]
    assert entry["path"] == "foo.py"
    assert entry["written"] is True
    assert entry["after"] == rc._sha256(ws / "foo.py")
    assert entry["before"] != entry["after"]


def _git(ws: Path, *args: str) -> str:
    identity = ["-c", "user.name=d", "-c", "user.email=d@example.invalid"]
    return subprocess.run(
        ["git", *identity, *args], cwd=ws, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_the_worktree_apply_records_each_write_and_delete(ws: Path) -> None:
    _git(ws, "init", "-q")
    (ws / "a.txt").write_text("a\n", encoding="utf-8")
    (ws / "gone.txt").write_text("gone\n", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", "base")
    base = _git(ws, "rev-parse", "HEAD")
    (ws / "a.txt").write_text("a changed\n", encoding="utf-8")
    (ws / "gone.txt").unlink()
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", "step")
    step = _git(ws, "rev-parse", "HEAD")
    _git(ws, "reset", "-q", "--hard", base)

    checkpoint = _started(ws)
    with undo_backup.turn(ws), rc.recording(checkpoint):
        rc.step_started(1)
        outcome = apply_commit_to_working_tree(ws, base, step)
        on_disk = rc.load(ws, "r1")

    assert sorted(outcome.applied) == ["a.txt", "gone.txt"]
    assert on_disk is not None
    entries = {e["path"]: e for e in on_disk["in_progress"]["files"]}
    assert entries["a.txt"]["written"] is True
    assert entries["a.txt"]["after"] == rc._sha256(ws / "a.txt")
    assert entries["gone.txt"]["written"] is True
    assert entries["gone.txt"]["after"] is None
