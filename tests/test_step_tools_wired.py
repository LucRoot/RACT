"""B-110 D5 and D6, wired: a write step works through the tools in its worktree.

A real turn against the fake model server with ``agent.step_tools: true``.
The model reads the file, edits it with the digest it read, and creates a
second file; the step's own file passes the executor's checks, and both
reach the operator's tree only through the substrate's apply. A tier-2 call
with nobody to answer is refused, and the model's own claim does not change
that.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ract import undo_backup
from ract.session_events import EventStream, SessionEvent
from ract.session_turn import TurnRequest, run_turn
from tests.fixtures.fake_model_server import Scenario
from tests.test_session_turn import _repo
from tests.ux import run_baseline as rb

CALC = rb.CALC_FILES["src/calc.py"]
FIXED = CALC.replace("return a - b\n\n\ndef sub", "return a + b\n\n\ndef sub")
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
FIX_ARGS = {
    "path": "src/calc.py",
    "old": "    return a - b\n\n\ndef sub",
    "new": "    return a + b\n\n\ndef sub",
}

Turn = Callable[[str], dict[str, Any]]


def _text(content: str) -> dict[str, Any]:
    return {"reply": {"kind": "text", "content": content}}


def _calls(*calls: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    envelopes = [{"tool": name, "arguments": args} for name, args in calls]
    return _text(json.dumps(envelopes[0] if len(envelopes) == 1 else envelopes))


def _workspace(tmp_path: Path, fake_model_server: Any, *tool_turns: Turn) -> Path:
    """A committed project with step_tools on, served by the scripted turns.

    Each of *tool_turns* is given the digest of src/calc.py as written (CRLF
    on Windows): the scripted model sends it, where a real model takes it
    from read_file.
    """
    ws = _repo(tmp_path, "http://127.0.0.1:9/v1")
    digest = hashlib.sha256((ws / "src" / "calc.py").read_bytes()).hexdigest()
    turns = [_text(json.dumps(PLAN)), *(turn(digest) for turn in tool_turns)]
    turns.append({**_text(json.dumps({"final": "add() adds now."})), "repeat": True})
    server = fake_model_server(
        Scenario.from_dict({"name": "b110_step_tools", "turns": turns})
    )
    rb._configure(ws, server.base_url, "fake-coder")
    config = ws / "ract.yaml"
    config.write_text(
        config.read_text(encoding="utf-8") + "\nagent:\n  step_tools: true\n",
        encoding="utf-8",
    )
    return ws


def _text_of(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _turn(ws: Path) -> tuple[int, list[SessionEvent]]:
    stream = EventStream(session="s-b110")
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    request = TurnRequest(
        config=ws / "ract.yaml", intent="fix add", session_id="s-b110", resume=False
    )
    code = run_turn(stream, request, turn=1, cancel=threading.Event())
    return code, events


def _errors(events: list[SessionEvent]) -> list[Any]:
    return [
        e.data
        for e in events
        if e.kind == "error.surfaced"
        or (e.kind == "tool.call.finished" and not e.data["ok"])
    ]


def test_a_write_step_edits_through_the_tools_and_the_apply(
    tmp_path: Path, fake_model_server: Any
) -> None:
    ws = _workspace(
        tmp_path,
        fake_model_server,
        lambda _d: _calls(("read_file", {"path": "src/calc.py"})),
        lambda digest: _calls(
            ("edit_file", {**FIX_ARGS, "expected_digest": digest}),
            (
                "write_file",
                {
                    "path": "notes/fix.md",
                    "content": "add() returned a - b.\n",
                    "create": True,
                },
            ),
        ),
    )

    code, events = _turn(ws)

    assert code == 0, _errors(events)
    assert _text_of(ws / "src" / "calc.py") == FIXED
    assert _text_of(ws / "notes" / "fix.md") == "add() returned a - b.\n"
    finished = events[-1].data
    assert finished["outcome"] == "done"
    assert "src/calc.py" in finished["changed"]
    assert any(
        e.kind == "notice" and "also changed notes/fix.md" in e.data.get("text", "")
        for e in events
    )
    # The tool calls are on the stream as cards.
    tools = [e.data["tool"] for e in events if e.kind == "tool.call.started"]
    assert tools == ["read_file", "edit_file", "write_file"]
    # /undo takes the step's own file back (B-049 records every applied path).
    undone = undo_backup.undo(ws)
    assert _text_of(ws / "src" / "calc.py") == CALC, undone


def test_a_tier_2_call_with_nobody_to_answer_is_refused(
    tmp_path: Path, fake_model_server: Any
) -> None:
    ws = _workspace(
        tmp_path,
        fake_model_server,
        lambda _d: _calls(
            (
                "write_file",
                {
                    "path": ".github/workflows/ci.yml",
                    "content": "on: push\n",
                    "create": True,
                },
            )
        ),
        lambda digest: _calls(("edit_file", {**FIX_ARGS, "expected_digest": digest})),
    )

    code, events = _turn(ws)

    assert code == 0, _errors(events)
    assert not (ws / ".github").exists()
    assert _text_of(ws / "src" / "calc.py") == FIXED
    refused = [
        e.data for e in events if e.kind == "tool.call.finished" and not e.data["ok"]
    ]
    assert [r["summary"].split("(")[0] for r in refused] == ["write_file"]
    assert "tier-2" in refused[0]["hint"]


def test_a_step_that_never_writes_its_file_applies_nothing(
    tmp_path: Path, fake_model_server: Any
) -> None:
    ws = _workspace(
        tmp_path,
        fake_model_server,
        lambda _d: _calls(
            ("write_file", {"path": "notes/only.md", "content": "x\n", "create": True})
        ),
    )

    code, events = _turn(ws)

    assert code != 0
    assert not (ws / "notes").exists()  # the worktree's change never reached the tree
    assert _text_of(ws / "src" / "calc.py") == CALC
    assert "ended without changing src/calc.py" in _errors(events)[0]["message"]


def test_step_tools_off_keeps_the_single_completion(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)

    code, events = _turn(ws)

    assert code == 0
    assert not [e for e in events if e.kind == "tool.call.started"]
    assert "return a + b" in _text_of(ws / "src" / "calc.py")


def test_the_step_loop_stops_get_their_own_hints() -> None:
    from ract.session_turn import hint_for

    assert "agent.step_tools" in hint_for(
        "Step 1 ended without changing src/calc.py. Nothing was applied to your files."
    )
    assert "agent.max_tokens_per_step" in hint_for(
        "Step 1: The step used 1200 tokens, more than its 1000. Nothing was applied."
    )
