"""UX-12: `ract report --last` shows what the turn recorded, never a default.

The baseline J4 transcript: right after a turn whose plan assumed "the
failing test is caused by add() subtracting" with confidence 0.85, the
report said "Assumption: no plan" and "Confidence: 0.0". The session
record dropped the plan of every executed run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.test_headless import _ract
from tests.test_session_turn import _repo


def test_the_report_shows_the_plan_that_ran(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)

    run = _ract(
        ws, "run", "--config", "ract.yaml", "--yolo", "--session", "s1", "--", "fix add"
    )
    report = _ract(ws, "report", "--last", "--config", "ract.yaml")

    assert run.returncode == 0, run.stdout + run.stderr
    text = report.stdout + report.stderr
    assert "Assumption: The failing test is caused by add() subtracting." in text
    assert "Planner confidence: 0.85" in text
    assert "no plan" not in text and "Confidence: 0.0" not in text
    assert "Fix add() in src/calc.py so it adds -> src/calc.py" in text
    saved = json.loads((ws / ".ract" / "sessions" / "s1.json").read_text("utf-8"))
    assert saved["plan"]["confidence"] == 0.85


def test_a_turn_without_a_plan_says_so(tmp_path: Path) -> None:
    ws = _repo(tmp_path, "http://127.0.0.1:9/v1")  # nothing answers

    _ract(
        ws, "run", "--config", "ract.yaml", "--yolo", "--session", "s2", "--", "fix add"
    )
    report = _ract(ws, "report", "--last", "--config", "ract.yaml")

    text = report.stdout + report.stderr
    assert "Plan: not recorded for this turn" in text
    assert "Confidence" not in text and "no plan" not in text
