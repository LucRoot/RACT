"""B-110 D6: proposed -> reviewed -> applied, in the asking mode with step_tools on.

The step's changes stay in its commit while the operator answers each hunk at
the console; only what was kept is applied, through the digest-checked apply.
A rejected hunk never reaches the live tree, not even for a moment: the tests
read the live file from inside the review's questions.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from ract.review_hunks import ReviewStopped, proposed_hunks, review_proposed_file
from ract.session_events import EventStream, SessionEvent
from ract.session_turn import TurnRequest, run_turn
from tests.test_step_tools_wired import FIX_ARGS, _calls, _text_of, _workspace

FILL = b"".join(b"# line %d\n" % i for i in range(12))  # keeps the two hunks apart
OLD = (
    b"def add(a, b):\n    return a - b\n" + FILL + b"def sub(a, b):\n    return a - b\n"
)
NEW = (
    b"def add(a, b):\n    return a + b\n" + FILL + b"def sub(a, b):\n    return b - a\n"
)


def _asker(*answers: str):
    queue = list(answers)

    def ask(_question: str) -> str | None:
        return queue.pop(0) if queue else None

    return ask


# ------------------------------------------------------------------ the core


def test_two_hunks_one_kept_one_rejected() -> None:
    shown: list[str] = []
    decision = review_proposed_file(
        "src/calc.py", OLD, NEW, _asker("a", "r"), shown.append, 80
    )
    assert decision.content == (
        b"def add(a, b):\n    return a + b\n"
        + FILL
        + b"def sub(a, b):\n    return a - b\n"
    )
    assert decision.answers == {1: "accepted", 2: "rejected"}
    assert any("Hunk 2 of 2" in line for line in shown)


def test_reject_all_gives_the_base_bytes_back() -> None:
    decision = review_proposed_file("src/calc.py", OLD, NEW, _asker("R"), print, 80)
    assert decision.content == OLD


def test_a_new_file_rejected_is_not_created() -> None:
    decision = review_proposed_file("notes.md", None, b"x\n", _asker("r"), print, 80)
    assert decision.content is None and decision.answers == {1: "rejected"}


def test_a_removal_kept_or_refused() -> None:
    assert review_proposed_file("a.txt", OLD, None, _asker("k"), print).content is None
    assert review_proposed_file("a.txt", OLD, None, _asker("r"), print).content == OLD


def test_end_of_input_stops_the_review() -> None:
    with pytest.raises(ReviewStopped):
        review_proposed_file("src/calc.py", OLD, NEW, _asker("a"), print, 80)


def test_the_proposed_hunks_carry_ids_and_escaped_text() -> None:
    hunks = proposed_hunks("x.py", b"a = 1\n", b"a = '\x1b[31m'\n")
    assert hunks[0]["id"] == 1 and hunks[0]["added"] == 1 and hunks[0]["removed"] == 1
    assert "\x1b" not in hunks[0]["text"]


# ------------------------------------------------------------------ a real turn


def _turn(ws: Path) -> tuple[int, list[SessionEvent]]:
    stream = EventStream(session="s-b110r")
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="fix add",
        session_id="s-b110r",
        resume=False,
        auto=True,  # the asking mode: proposed changes are reviewed
    )
    code = run_turn(stream, request, turn=1, cancel=threading.Event())
    return code, events


def _two_files(tmp_path: Path, fake_model_server: Any) -> Path:
    return _workspace(
        tmp_path,
        fake_model_server,
        lambda digest: _calls(
            ("edit_file", {**FIX_ARGS, "expected_digest": digest}),
            (
                "write_file",
                {"path": "notes/fix.md", "content": "a note\n", "create": True},
            ),
        ),
    )


def _console(monkeypatch, ws: Path, answers: list[str]) -> list[str]:
    """Answer the review at the console; record the live calc.py at each question."""
    seen: list[str] = []

    def read_line(prompt: str) -> str:
        seen.append(_text_of(ws / "src" / "calc.py"))
        if not answers:
            raise EOFError
        return answers.pop(0)

    monkeypatch.setattr("ract.approval_callback.read_line", read_line)
    return seen


def test_the_review_keeps_one_file_and_rejects_the_other(
    tmp_path: Path, fake_model_server: Any, monkeypatch
) -> None:
    ws = _two_files(tmp_path, fake_model_server)
    before = _text_of(ws / "src" / "calc.py")
    # git lists notes/fix.md first: restore it (r), then keep the calc.py hunk (a).
    seen = _console(monkeypatch, ws, ["r", "a"])

    code, events = _turn(ws)

    assert code == 0, [e.data for e in events if e.kind == "error.surfaced"]
    assert seen and all(text == before for text in seen)  # nothing applied while asked
    assert "return a + b" in _text_of(ws / "src" / "calc.py")
    assert not (ws / "notes").exists()  # rejected: never written
    proposed = [e.data["path"] for e in events if e.kind == "diff.proposed"]
    assert sorted(proposed) == ["notes/fix.md", "src/calc.py"]
    reviewed = {
        (e.data["path"], e.data["decision"])
        for e in events
        if e.kind == "diff.reviewed"
    }
    assert reviewed == {("src/calc.py", "accepted"), ("notes/fix.md", "rejected")}
    applied = next(e.data for e in events if e.kind == "change.applied")
    assert applied["paths"] == ["src/calc.py"] and applied["checkpoint"]


def test_rejecting_everything_changes_nothing(
    tmp_path: Path, fake_model_server: Any, monkeypatch
) -> None:
    ws = _two_files(tmp_path, fake_model_server)
    before = (ws / "src" / "calc.py").read_bytes()
    _console(monkeypatch, ws, ["R", "r"])

    code, events = _turn(ws)

    assert code == 0, [e.data for e in events if e.kind == "error.surfaced"]
    assert (ws / "src" / "calc.py").read_bytes() == before
    assert not (ws / "notes").exists()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "src", "notes"],
        cwd=ws,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert status == ""


def test_a_review_that_ends_unanswered_applies_nothing(
    tmp_path: Path, fake_model_server: Any, monkeypatch
) -> None:
    ws = _two_files(tmp_path, fake_model_server)
    before = (ws / "src" / "calc.py").read_bytes()
    _console(monkeypatch, ws, ["a"])  # then end of input at the second file

    code, events = _turn(ws)

    assert code != 0
    assert (ws / "src" / "calc.py").read_bytes() == before  # the kept hunk waits too
    assert not (ws / "notes").exists()
    error = next(e.data for e in events if e.kind == "error.surfaced")
    assert "ended without an answer" in error["message"]
    assert "rootact/step/" in error["message"]


def test_without_someone_to_ask_the_step_applies_as_proposed(
    tmp_path: Path, fake_model_server: Any
) -> None:
    from tests.test_step_tools_wired import _turn as unattended_turn

    ws = _two_files(tmp_path, fake_model_server)

    code, events = unattended_turn(ws)

    assert code == 0
    assert not [e for e in events if e.kind == "diff.proposed"]
    assert (ws / "notes" / "fix.md").exists()


def test_the_step_question_is_not_asked_twice(monkeypatch) -> None:
    from ract.approval_callback import review_replaces_step_question
    from ract.manager import Step

    asked: list[Step] = []
    callback = review_replaces_step_question(lambda step: asked.append(step) or False)
    assert callback(Step(action="fix", provider_hint="local", expected_artifact="a.py"))
    tool = Step(  # a tool call still asks first
        action="run",
        provider_hint="local",
        expected_artifact="",
        tool_call={"tool": "x"},
    )
    assert callback(tool) is False and asked == [tool]


def test_the_scenario_reply_is_json() -> None:
    # Guard for the helpers this file borrows: a reply is one JSON value.
    reply = _calls(("read_file", {"path": "a"}))["reply"]["content"]
    assert json.loads(reply)["tool"] == "read_file"


def test_a_whole_file_question_says_apply_and_leave_out() -> None:
    questions: list[str] = []

    def ask(question: str) -> str:
        questions.append(question)
        return "r"

    # A file that is not UTF-8 text is one question, not hunks.
    decision = review_proposed_file("logo.bin", None, b"\xff\xfe\x00x", ask, print, 80)
    assert decision.content is None
    changed = review_proposed_file("logo.bin", b"\xff", b"\xfe", ask, print, 80)
    assert changed.content == b"\xff"
    assert questions == [
        "Apply the step's new file logo.bin? [a apply, r leave it out]: ",
        "Apply the step's change to logo.bin? [a apply, r leave it out]: ",
    ]
    assert not any("restore" in q for q in questions)  # nothing was saved yet


def test_the_proposed_event_renders_one_line(tmp_path: Path) -> None:
    from ract.session_render import PlainRenderer

    out: list[str] = []
    stream = EventStream(session="s")
    stream.subscribe(PlainRenderer(out.append))
    stream.emit(
        "diff.proposed",
        {
            "path": "src/\x1b[31mcalc.py",
            "hunks": proposed_hunks("x.py", OLD, NEW),
            "tier": "T1",
        },
        turn=1,
    )
    text = "".join(out)
    lines = text.strip().splitlines()
    assert len(lines) == 1 and lines[0].endswith("calc.py (proposed, T1): 2 hunks")
    assert "\x1b" not in text  # the path's escape sequence never reaches the screen


def test_a_proposed_control_file_is_shown_as_tier_2(
    tmp_path: Path, fake_model_server: Any, monkeypatch
) -> None:
    from ract import tier2_approvals

    ws = _workspace(
        tmp_path,
        fake_model_server,
        lambda digest: _calls(
            ("edit_file", {**FIX_ARGS, "expected_digest": digest}),
            ("write_file", {"path": "AGENTS.md", "content": "x\n", "create": True}),
        ),
    )
    tier2_approvals._LIVE.clear()
    _console(monkeypatch, ws, ["y", "a", "a"])  # the tier-2 question, then two hunks

    code, events = _turn(ws)

    assert code == 0, [e.data for e in events if e.kind == "error.surfaced"]
    tiers = {
        e.data["path"]: e.data["tier"] for e in events if e.kind == "diff.proposed"
    }
    assert tiers == {"AGENTS.md": "T2", "src/calc.py": "T1"}
