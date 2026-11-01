"""B-039: ``ract verify`` (ADR-0050 as amended by D-174).

Real turns on the fake model server sign what they write (S-015b). The
range check attributes every changed line to a recorded step; the run
check verifies the trace chain when the run has one. Every report ends
with the commands.jsonl statement. The tests use throwaway keys in the
test's own state folder (conftest isolates LOCALAPPDATA and
XDG_STATE_HOME); never the operator's.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

from ract.session_events import EventStream, SessionEvent
from ract.session_turn import TurnRequest, run_turn
from ract.verify_cli import (
    CLOSE_STATEMENT,
    TRACE_NONE,
    verify_command,
)
from tests.test_session_turn import _repo


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )


def _commit_all(ws: Path, message: str) -> str:
    _git(ws, "add", "-A")
    _git(
        ws, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
        "commit", "-q", "-m", message,
    )
    return _git(ws, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def signed_repo(tmp_path: Path, fake_model_server) -> tuple[Path, str, str, str]:
    """A repo where a real turn wrote and signed src/calc.py, committed.

    Returns ``(repo, from_commit, to_commit, run_id)``: ``from_commit``
    predates the turn; ``to_commit`` holds the tree the turn left.
    """
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    if not (ws / ".git").is_dir():
        _git(ws, "init", "-q", "-b", "main")
    before = _commit_all(ws, "base")

    events: list[SessionEvent] = []
    stream = EventStream(session="s-b039")
    stream.subscribe(events.append)
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="fix add in src/calc.py",
        session_id="s-b039",
        resume=False,
        auto=False,
    )
    code = run_turn(stream, request, turn=1, cancel=threading.Event())
    assert code == 0, [e.data for e in events if e.kind == "error.surfaced"]
    sidecar = ws / "src" / ".calc.py.rootknot.json"
    assert sidecar.is_file(), "the turn did not sign its file"
    run_id = json.loads(sidecar.read_text(encoding="utf-8"))["run_id"]
    after = _commit_all(ws, "turn")
    return ws, before, after, run_id


def test_a_signed_file_verifies_in_a_range(signed_repo, capsys) -> None:
    ws, before, after, _run_id = signed_repo
    code = verify_command(["--repo", str(ws), f"{before}..{after}"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "attributed and verified" in out
    assert "src/calc.py" in out
    assert out.rstrip().endswith(CLOSE_STATEMENT)


def test_a_tampered_file_fails(signed_repo, capsys) -> None:
    ws, before, _after, _run_id = signed_repo
    # Change the file's committed bytes without re-signing: amend the turn
    # commit so the bytes at the tip no longer match the knot's digest.
    (ws / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a + b + 1\n", encoding="utf-8"
    )
    new_after = _commit_all_amend(ws)
    code = verify_command(["--repo", str(ws), f"{before}..{new_after}"])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "changed since it was signed" in out
    assert out.rstrip().endswith(CLOSE_STATEMENT)


def _commit_all_amend(ws: Path) -> str:
    _git(ws, "add", "-A")
    _git(
        ws, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
        "commit", "-q", "--amend", "-m", "turn",
    )
    return _git(ws, "rev-parse", "HEAD").stdout.strip()


def test_a_line_no_step_wrote_is_not_written_by_ract(signed_repo, capsys) -> None:
    ws, before, _after, _run_id = signed_repo
    # A file the operator wrote and committed: no sidecar, no index row.
    (ws / "NOTES.md").write_text("my own notes\n", encoding="utf-8")
    new_after = _commit_all(ws, "notes")
    code = verify_command(["--repo", str(ws), f"{before}..{new_after}"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "not written by RACT" in out
    assert "NOTES.md" in out
    assert out.rstrip().endswith(CLOSE_STATEMENT)
    # With --strict the unattributed line fails the run.
    code = verify_command(["--repo", str(ws), f"{before}..{new_after}", "--strict"])
    out = capsys.readouterr().out
    assert code == 1, out
    assert out.rstrip().endswith(CLOSE_STATEMENT)


def test_a_run_without_a_trace_prints_the_fact(signed_repo, capsys) -> None:
    ws, _before, _after, run_id = signed_repo
    code = verify_command(["--repo", str(ws), "--run", run_id])
    out = capsys.readouterr().out
    assert TRACE_NONE in out
    assert out.rstrip().endswith(CLOSE_STATEMENT)
    # Nothing was checkable: the nothing-to-check exit code.
    assert code == 2


def test_the_report_shows_range_and_run(signed_repo, capsys) -> None:
    ws, before, after, run_id = signed_repo
    code = verify_command(["--repo", str(ws), f"{before}..{after}", "--run", run_id])
    out = capsys.readouterr().out
    assert code == 0, out
    assert before[:12] in out and after[:12] in out
    assert run_id in out
    assert TRACE_NONE in out  # no trace was written for this run (D-166)
    assert out.rstrip().endswith(CLOSE_STATEMENT)


def test_a_range_and_a_run_are_required() -> None:
    with pytest.raises(SystemExit) as exc:
        verify_command([])
    assert exc.value.code == 2
