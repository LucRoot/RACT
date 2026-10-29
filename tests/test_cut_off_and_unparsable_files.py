"""B-095 (S2 D1, D2): a cut-off reply or a new file that does not parse is not done.

Each test is a real ``ract -p --accept-edits`` process on the fake server. The
plan has one step that creates ``src/notes.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.fixtures.fake_model_server import Scenario
from tests.test_headless import _ract
from tests.test_session_turn import _repo

PLAN = json.dumps(
    {
        "assumption": "A notes module is wanted.",
        "confidence": 0.8,
        "steps": [
            {
                "action": "Add src/notes.py with a documented NOTE constant",
                "provider_hint": "local",
                "expected_artifact": "src/notes.py",
            }
        ],
    }
)
GOOD = '"""Notes."""\n\nNOTE = "two"\n'
CUT_IN_DOCSTRING = '"""Notes for the calculator.\n\nThis module keeps the'


def _scenario(*replies: dict[str, Any]) -> Scenario:
    turns = [{"reply": {"kind": "text", "content": PLAN}}]
    turns += [{"reply": r} for r in replies]
    turns += [{"reply": {"kind": "text", "content": "Done."}}] * 3
    return Scenario.from_dict({"turns": turns})


def _run(tmp_path: Path, fake_model_server: Any, *replies: dict[str, Any]):
    server = fake_model_server(_scenario(*replies))
    ws = _repo(tmp_path, server.base_url)
    result = _ract(
        ws, "-p", "add a notes module", "--accept-edits", "--output-format", "text"
    )
    return ws, result, server


def test_a_reply_cut_at_the_limit_is_asked_again_and_the_full_file_written(
    tmp_path: Path, fake_model_server: Any
) -> None:
    ws, result, server = _run(
        tmp_path,
        fake_model_server,
        {"kind": "truncated", "content": CUT_IN_DOCSTRING},
        {"kind": "text", "content": GOOD},
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert (ws / "src" / "notes.py").read_text(encoding="utf-8") == GOOD
    assert "cut off" in out
    assert "stopped before the file was complete" in json.dumps(
        server.chat_requests[2].body
    )


def test_a_reply_that_ends_inside_a_docstring_counts_as_cut_off(
    tmp_path: Path, fake_model_server: Any
) -> None:
    ws, result, _ = _run(
        tmp_path,
        fake_model_server,
        {"kind": "text", "content": CUT_IN_DOCSTRING, "finish_reason": "stop"},
        {"kind": "text", "content": GOOD},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (ws / "src" / "notes.py").read_text(encoding="utf-8") == GOOD


def test_cut_off_twice_writes_nothing_and_says_so(
    tmp_path: Path, fake_model_server: Any
) -> None:
    ws, result, server = _run(
        tmp_path,
        fake_model_server,
        {"kind": "truncated", "content": CUT_IN_DOCSTRING},
        {"kind": "truncated", "content": CUT_IN_DOCSTRING},
    )
    out = result.stdout + result.stderr
    assert result.returncode != 0
    assert "cut off twice" in out and "Nothing was written" in out
    assert "max_tokens" in out
    assert not (ws / "src" / "notes.py").exists()
    assert len(server.chat_requests) == 3  # the plan, the step, one retry


def test_a_new_python_file_that_does_not_parse_is_refused_with_its_line(
    tmp_path: Path, fake_model_server: Any
) -> None:
    ws, result, _ = _run(
        tmp_path,
        fake_model_server,
        {"kind": "text", "content": "NOTE = (\n    'two'\n\ndef f(:\n    pass\n"},
    )
    out = result.stdout + result.stderr
    assert result.returncode != 0
    assert "refused to create src/notes.py" in out
    assert "not valid python (line" in out
    assert not (ws / "src" / "notes.py").exists()


def test_a_valid_new_file_is_written_with_one_request(
    tmp_path: Path, fake_model_server: Any
) -> None:
    ws, result, server = _run(
        tmp_path, fake_model_server, {"kind": "text", "content": GOOD}
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (ws / "src" / "notes.py").read_text(encoding="utf-8") == GOOD
    assert "cut off" not in result.stdout + result.stderr
    assert len(server.chat_requests) >= 2
    step_requests = [
        r
        for r in server.chat_requests
        if "Expected artifact: src/notes.py" in json.dumps(r.body)
    ]
    assert len(step_requests) == 1
