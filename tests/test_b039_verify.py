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
import sys
import threading
from pathlib import Path

import pytest

from ract.session_events import EventStream, SessionEvent
from ract.session_turn import TurnRequest, run_turn
from ract.verify_cli import (
    CLOSE_STATEMENT,
    TRACE_NONE,
    NOT_WRITTEN,
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


def test_close_statement_names_the_state_dir_command_records() -> None:
    # B-236: the only writer is tools/command.py:_record, which appends to
    # <state>/keys/<repo-digest>/commands.jsonl in the user state dir. No
    # writer has ever put records at a workspace-local .ract/commands.jsonl,
    # so the statement must not name it.
    assert ".ract/commands.jsonl" not in CLOSE_STATEMENT
    assert "keys/<repo-digest>/commands.jsonl" in CLOSE_STATEMENT
    assert "user state dir" in CLOSE_STATEMENT


# B-236: the clean-working-tree fallback applies only when the later
# commit is HEAD; a path under .ract/ is not RACT's own record; sidecars
# are read from the later commit when it is not HEAD.


def _run_signed_turn(ws: Path, server) -> None:
    events: list[SessionEvent] = []
    stream = EventStream(session="s-b236")
    stream.subscribe(events.append)
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="fix add in src/calc.py",
        session_id="s-b236",
        resume=False,
        auto=False,
    )
    code = run_turn(stream, request, turn=1, cancel=threading.Event())
    assert code == 0, [e.data for e in events if e.kind == "error.surfaced"]
    assert (ws / "src" / ".calc.py.rootknot.json").is_file()


@pytest.fixture
def filtered_repo(
    tmp_path: Path, fake_model_server
) -> tuple[Path, str, str]:
    """A signed turn whose commit blob differs from the signed bytes.

    A clean filter rewrites what git stores (``return a + b`` becomes
    ``return (a + b)`` in every blob) and the smudge filter is its inverse,
    so whichever way the harness restores the file, the working tree ends
    up holding the signed bytes while the committed blob never matches the
    knot, and the path stays clean against HEAD. Returns
    ``(repo, before, after)``.
    """
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    if not (ws / ".git").is_dir():
        _git(ws, "init", "-q", "-b", "main")
    filter_script = tmp_path / "roundtrip_filter.py"
    filter_script.write_text(
        "import sys\n"
        "data = sys.stdin.buffer.read()\n"
        'sys.stdout.buffer.write(data.replace(b"return a + b", b"return (a + b)"))\n',
        encoding="utf-8",
    )
    unfilter_script = tmp_path / "roundtrip_unfilter.py"
    unfilter_script.write_text(
        "import sys\n"
        "data = sys.stdin.buffer.read()\n"
        'sys.stdout.buffer.write(data.replace(b"return (a + b)", b"return a + b"))\n',
        encoding="utf-8",
    )
    _git(
        ws, "config", "filter.tamper.clean",
        f'"{sys.executable}" "{filter_script}"',
    )
    _git(
        ws, "config", "filter.tamper.smudge",
        f'"{sys.executable}" "{unfilter_script}"',
    )
    (ws / ".gitattributes").write_text("src/calc.py filter=tamper\n")
    before = _commit_all(ws, "base")
    _run_signed_turn(ws, server)
    after = _commit_all(ws, "turn")
    return ws, before, after


def test_the_line_ending_fallback_never_fires_before_head(filtered_repo, capsys) -> None:
    ws, before, after = filtered_repo
    # A later commit, so `after` is not HEAD and the working tree still
    # holds the signed bytes, clean against HEAD.
    (ws / "NOTES.md").write_text("later\n", encoding="utf-8")
    _commit_all(ws, "later")
    code = verify_command(["--repo", str(ws), f"{before}..{after}"])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "changed since it was signed" in out
    assert "attributed and verified" not in out
    assert out.rstrip().endswith(CLOSE_STATEMENT)


def test_the_line_ending_fallback_still_fires_at_head(filtered_repo, capsys) -> None:
    ws, before, after = filtered_repo
    # At HEAD the fallback is the declared line-ending normalization: the
    # digest matches the bytes as this checkout holds them.
    code = verify_command(["--repo", str(ws), f"{before}..{after}"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "attributed and verified" in out
    assert "line endings" in out
    assert out.rstrip().endswith(CLOSE_STATEMENT)


def test_a_path_under_dot_ract_is_not_racts_own_record(signed_repo, capsys) -> None:
    ws, before, _after, _run_id = signed_repo
    state = ws / ".ract"
    state.mkdir(exist_ok=True)
    (state / "notes.txt").write_text("state a person wrote\n", encoding="utf-8")
    (state / ".meta.rootknot.json").write_text("{}\n", encoding="utf-8")
    _git(ws, "add", "-f", ".ract/notes.txt", ".ract/.meta.rootknot.json")
    new_after = _commit_all(ws, "state files")
    code = verify_command(["--repo", str(ws), f"{before}..{new_after}"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert ".ract/notes.txt" in out
    assert NOT_WRITTEN in out
    # Only the sidecar-looking name keeps the exemption.
    assert ".ract/.meta.rootknot.json: RACT's own sidecar record" in out
    assert out.rstrip().endswith(CLOSE_STATEMENT)
    code = verify_command(["--repo", str(ws), f"{before}..{new_after}", "--strict"])
    out = capsys.readouterr().out
    assert code == 1, out
    assert out.rstrip().endswith(CLOSE_STATEMENT)


def test_the_sidecar_is_read_from_the_later_commit(signed_repo, capsys) -> None:
    ws, before, after, _run_id = signed_repo
    # Move HEAD so `after` is not HEAD, then corrupt the working-tree
    # sidecar. The commit's copy is intact and must be the one read: the
    # verdict is the strict bytes-at-commit check, not the tree's
    # "unparseable".
    (ws / "NOTES.md").write_text("later\n", encoding="utf-8")
    _commit_all(ws, "later")
    (ws / "src" / ".calc.py.rootknot.json").write_text(
        "{not json", encoding="utf-8"
    )
    code = verify_command(["--repo", str(ws), f"{before}..{after}"])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "changed since it was signed" in out
    assert "unparseable" not in out
    assert out.rstrip().endswith(CLOSE_STATEMENT)


def test_a_deleted_signed_file_is_attributed_at_the_earlier_commit(
    tmp_path: Path, fake_model_server, capsys
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    if not (ws / ".git").is_dir():
        _git(ws, "init", "-q", "-b", "main")
    # No line-ending normalization, so the committed blob is exactly the
    # bytes the turn signed and the deleted-file check has no CRLF
    # conversion to account for.
    _git(ws, "config", "core.autocrlf", "false")
    _commit_all(ws, "base")
    _run_signed_turn(ws, server)
    # The earlier commit holds exactly what the turn signed; the later
    # commit deletes the file while its sidecar stays committed (only the
    # attested file is removed). The ADR's rule compares the bytes at the
    # later commit; a deleted file has none there, so the knot is checked
    # against the bytes at the earlier commit and the report says so.
    after = _commit_all(ws, "turn")
    (ws / "src" / "calc.py").unlink()
    deleted_at = _commit_all(ws, "delete calc")
    code = verify_command(["--repo", str(ws), f"{after}..{deleted_at}"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "D src/calc.py" in out
    assert f"deleted at {deleted_at[:12]}" in out
    assert f"content at {after[:12]}" in out
    assert "attributed and verified" in out
    assert out.rstrip().endswith(CLOSE_STATEMENT)


def test_a_deleted_signed_file_verifies_under_crlf_normalization(
    tmp_path: Path, fake_model_server, capsys
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    if not (ws / ".git").is_dir():
        _git(ws, "init", "-q", "-b", "main")
    # The repository normalizes line endings on commit: under
    # core.autocrlf true the committed blob is LF while the sidecar signs
    # the CRLF disk bytes the step wrote.
    _git(ws, "config", "core.autocrlf", "true")
    _commit_all(ws, "base")
    _run_signed_turn(ws, server)
    after = _commit_all(ws, "turn")
    disk = (ws / "src" / "calc.py").read_bytes()
    blob = _git(ws, "show", f"{after}:src/calc.py").stdout
    if b"\r\n" not in disk or "\r" in blob:
        pytest.skip(
            "this platform stored the signed bytes as LF, so the CRLF "
            "premise of the defect does not arise here"
        )
    (ws / "src" / "calc.py").unlink()
    deleted_at = _commit_all(ws, "delete calc")
    code = verify_command(["--repo", str(ws), f"{after}..{deleted_at}"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "D src/calc.py" in out
    assert "attributed and verified" in out
    assert out.rstrip().endswith(CLOSE_STATEMENT)


def test_a_working_tree_record_is_named_when_not_at_head(
    tmp_path: Path, fake_model_server, capsys
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    if not (ws / ".git").is_dir():
        _git(ws, "init", "-q", "-b", "main")
    before = _commit_all(ws, "base")
    _run_signed_turn(ws, server)
    # Commit the turn's file without its sidecar: the knot record exists
    # only in the working tree, and the report must say plainly that it
    # read it there, because the later commit is not HEAD.
    with (ws / ".git" / "info" / "exclude").open("a", encoding="utf-8") as fh:
        fh.write("src/.calc.py.rootknot.json\n")
    after = _commit_all(ws, "turn")
    (ws / "NOTES.md").write_text("later\n", encoding="utf-8")
    _commit_all(ws, "later")
    code = verify_command(["--repo", str(ws), f"{before}..{after}"])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "changed since it was signed" in out
    assert "the knot record was read from the working tree" in out
    assert "not HEAD" in out
    assert out.rstrip().endswith(CLOSE_STATEMENT)
