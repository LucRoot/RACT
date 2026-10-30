"""B-110 D6: a step that changes files in a folder that is not a git repository.

With ``agent.step_tools`` on, edits happen in a worktree, so the first change
is an offer to run ``git init`` plus an initial commit, as a tier-2 action.
Only the operator's yes runs it; sensitive files are left out of the commit.
On no, or with nobody to ask, nothing is changed and the error says how to
enable edits later.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any

from ract.executor.worktree import init_preview, init_repository
from ract.session_events import EventStream, SessionEvent
from ract.session_turn import TurnRequest, run_turn
from tests.test_step_tools_wired import FIX_ARGS, _calls, _text_of
from tests.ux import run_baseline as rb
from tests.fixtures.fake_model_server import Scenario

import hashlib
import json

PLAN = {
    "assumption": "add() subtracts.",
    "confidence": 0.9,
    "steps": [
        {
            "action": "Fix add() in src/calc.py so it adds",
            "provider_hint": "local",
            "expected_artifact": "src/calc.py",
        }
    ],
}


def _folder(tmp_path: Path, fake_model_server: Any) -> Path:
    ws = rb._workspace(tmp_path, "plain", git=False, files=rb.CALC_FILES)
    (ws / ".env").write_text("TOKEN=never-leave\n", encoding="utf-8")
    digest = hashlib.sha256((ws / "src" / "calc.py").read_bytes()).hexdigest()
    turns = [
        {"reply": {"kind": "text", "content": json.dumps(PLAN)}},
        _calls(("edit_file", {**FIX_ARGS, "expected_digest": digest})),
        {
            "reply": {"kind": "text", "content": json.dumps({"final": "done"})},
            "repeat": True,
        },
    ]
    server = fake_model_server(Scenario.from_dict({"name": "git_init", "turns": turns}))
    rb._configure(ws, server.base_url, "fake-coder")
    config = ws / "ract.yaml"
    config.write_text(
        config.read_text(encoding="utf-8") + "\nagent:\n  step_tools: true\n",
        encoding="utf-8",
    )
    return ws


def _turn(ws: Path, auto: bool) -> tuple[int, list[SessionEvent]]:
    stream = EventStream(session="s-init")
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="fix add",
        session_id="s-init",
        resume=False,
        auto=auto,
    )
    return run_turn(stream, request, turn=1, cancel=threading.Event()), events


def _answers(monkeypatch, *answers: str) -> list[str]:
    queue = list(answers)
    prompts: list[str] = []

    def read_line(prompt: str) -> str:
        prompts.append(prompt)
        if not queue:
            raise EOFError
        return queue.pop(0)

    monkeypatch.setattr("ract.approval_callback.read_line", read_line)
    return prompts


def test_yes_makes_a_repository_without_the_sensitive_file(
    tmp_path: Path, fake_model_server: Any, monkeypatch
) -> None:
    ws = _folder(tmp_path, fake_model_server)
    # y to the offer, then a to the one proposed hunk.
    prompts = _answers(monkeypatch, "y", "a")

    code, events = _turn(ws, auto=True)

    assert code == 0, [e.data for e in events if e.kind == "error.surfaced"]
    assert prompts[0].startswith("Run it? [y]es, approve")  # MASON's offer view
    assert "return a + b" in _text_of(ws / "src" / "calc.py")
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ws, capture_output=True, text=True, check=True
    ).stdout.split()
    assert "src/calc.py" in tracked and ".env" not in tracked
    assert (ws / ".env").read_text(encoding="utf-8") == "TOKEN=never-leave\n"


def test_no_changes_nothing_and_says_how(
    tmp_path: Path, fake_model_server: Any, monkeypatch
) -> None:
    ws = _folder(tmp_path, fake_model_server)
    before = (ws / "src" / "calc.py").read_bytes()
    _answers(monkeypatch, "n")

    code, events = _turn(ws, auto=True)

    assert code != 0
    assert not (ws / ".git").exists()
    assert (ws / "src" / "calc.py").read_bytes() == before
    error = next(e.data for e in events if e.kind == "error.surfaced")
    assert "you declined `git init`" in error["message"]


def test_with_nobody_to_ask_nothing_changes(
    tmp_path: Path, fake_model_server: Any
) -> None:
    ws = _folder(tmp_path, fake_model_server)
    before = (ws / "src" / "calc.py").read_bytes()

    code, events = _turn(ws, auto=False)

    assert code != 0
    assert not (ws / ".git").exists()
    assert (ws / "src" / "calc.py").read_bytes() == before
    error = next(e.data for e in events if e.kind == "error.surfaced")
    assert "nobody could answer" in error["message"]


def test_the_preview_counts_files_and_names_what_is_left_out(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("K=v\n", encoding="utf-8")
    (tmp_path / ".ract").mkdir()
    (tmp_path / ".ract" / "state.json").write_text("{}", encoding="utf-8")
    count, left_out = init_preview(tmp_path)
    assert count == 1 and left_out == [".env"]
    assert init_repository(tmp_path) == [".env"]
    log = subprocess.run(
        ["git", "log", "--format=%an %s"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip()
    assert log == "ract ract: initial commit of the current files"
