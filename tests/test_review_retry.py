"""B-061d: review: retry sends validated defects back to the step once (D14, D-093).

In-process turns on the fake server, so the retry bound can be lowered for the
budget case.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from ract.review import stage
from ract.session_events import EventStream
from ract.session_turn import TurnRequest, run_turn
from ract.tools import UNTRUSTED_LABEL
from tests.fixtures.fake_model_server import Scenario
from tests.test_session_turn import _repo

PLAN = json.dumps(
    {
        "assumption": "add() is wrong.",
        "confidence": 0.8,
        "steps": [
            {
                "action": "Fix add() in src/calc.py so it adds",
                "provider_hint": "local",
                "expected_artifact": "src/calc.py",
            }
        ],
    }
)
FIRST = "def add(a, b):\n    return a * b\n\n\ndef sub(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"


def _finding(path: str, line: int, evidence: str) -> dict[str, Any]:
    return {
        "path": path,
        "line": line,
        "severity": "defect",
        "claim": "add multiplies; the goal is to add",
        "evidence": evidence,
    }


def _turn(tmp_path: Path, fake_model_server: Any, *replies: dict[str, Any]):
    turns = [{"reply": {"kind": "text", "content": PLAN}}]
    turns += [{"reply": r} for r in replies]
    turns += [{"reply": {"kind": "text", "content": "Done."}}] * 3
    server = fake_model_server(Scenario.from_dict({"turns": turns}))
    ws = _repo(tmp_path, server.base_url)
    config = ws / "ract.yaml"
    config.write_text(
        config.read_text(encoding="utf-8") + "\nreview: retry\n", encoding="utf-8"
    )
    stream = EventStream(session="s-test")
    events: list[Any] = []
    stream.subscribe(events.append)
    request = TurnRequest(
        config=config,
        intent="fix add",
        session_id="s-test",
        resume=False,
    )
    run_turn(stream, request, turn=1, cancel=threading.Event())
    return ws, server, events


def _text(content: str) -> dict[str, Any]:
    return {"kind": "text", "content": content}


def _notices(events: list[Any]) -> list[str]:
    return [e.data["text"] for e in events if e.kind == "notice"]


def test_retry_mode_sends_validated_defects_back_once(
    tmp_path: Path, fake_model_server: Any
) -> None:
    review = {"findings": [_finding("src/calc.py", 2, "return a * b")]}
    ws, server, events = _turn(
        tmp_path,
        fake_model_server,
        _text(FIRST),
        _text(json.dumps(review)),
        _text(FIXED),
    )
    assert (ws / "src" / "calc.py").read_text(encoding="utf-8") == FIXED
    bodies = [json.dumps(r.body) for r in server.chat_requests]
    reviewer = [b for b in bodies if "You review one step" in b]
    retries = [b for b in bodies if "<review>" in b]
    assert len(reviewer) == 1 and len(retries) == 1
    assert "add multiplies" in retries[0] and UNTRUSTED_LABEL in retries[0]
    assert any("back to the step once" in n for n in _notices(events))
    finished = [e.data for e in events if e.kind == "turn.finished"][-1]
    assert finished["outcome"] == "done"


def test_a_retry_cannot_touch_a_file_the_step_did_not_change(
    tmp_path: Path, fake_model_server: Any
) -> None:
    review = {"findings": [_finding("README.md", 1, "# calc")]}
    ws, server, events = _turn(
        tmp_path, fake_model_server, _text(FIRST), _text(json.dumps(review))
    )
    bodies = [json.dumps(r.body) for r in server.chat_requests]
    assert not any("<review>" in b for b in bodies)
    assert (ws / "src" / "calc.py").read_text(encoding="utf-8") == FIRST
    assert (ws / "README.md").read_text(
        encoding="utf-8"
    ) == "# calc\n\nA tiny calculator library.\n"
    [review_event] = [e.data for e in events if e.kind == "review.finished"]
    assert [f["severity"] for f in review_event["findings"]] == ["note"]


def test_retry_budget_used_shows_findings_without_a_retry(
    tmp_path: Path, fake_model_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # B-095's cut-off retry uses the step's only retry here (bound lowered to 1).
    monkeypatch.setattr(stage, "MAX_STEP_RETRIES", 1)
    review = {"findings": [_finding("src/calc.py", 2, "return a * b")]}
    ws, server, events = _turn(
        tmp_path,
        fake_model_server,
        {"kind": "truncated", "content": "def add(a, b):\n    return '''cut"},
        _text(FIRST),
        _text(json.dumps(review)),
    )
    assert (ws / "src" / "calc.py").read_text(encoding="utf-8") == FIRST
    assert not any("<review>" in json.dumps(r.body) for r in server.chat_requests)
    assert any("retry budget used" in n for n in _notices(events))
