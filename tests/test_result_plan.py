"""B-053b: ract.result/1 carries the plan as an array, built from the run's events."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ract.headless import result_object
from ract.plan_state import plan_items
from ract.session_events import EventStream

ROOT = Path(__file__).resolve().parents[1]


def _events(*steps: tuple[str, dict]) -> list:
    stream = EventStream(
        session="s-1",
        clock=lambda: datetime(2026, 10, 23, 17, 0, tzinfo=timezone.utc),
    )
    collected: list = []
    stream.subscribe(collected.append)
    for kind, data in steps:
        stream.emit(kind, data, turn=1)
    return collected


def _plan(*actions: str) -> tuple[str, dict]:
    return (
        "plan.proposed",
        {
            "assumption": "",
            "confidence": 0.9,
            "steps": [
                {"n": i, "action": action, "target": f"f{i}.py"}
                for i, action in enumerate(actions, start=1)
            ],
        },
    )


def test_a_scripted_three_step_run_gives_three_items_in_order_with_final_states():
    events = _events(
        _plan("edit a", "edit b", "edit c"),
        ("step.started", {"n": 1, "action": "edit a", "target": "f1.py"}),
        ("step.finished", {"n": 1, "outcome": "done", "artifact": "f1.py"}),
        ("step.started", {"n": 2, "action": "edit b", "target": "f2.py"}),
        ("step.finished", {"n": 2, "outcome": "done", "artifact": "f2.py"}),
        ("step.started", {"n": 3, "action": "edit c", "target": "f3.py"}),
        ("step.finished", {"n": 3, "outcome": "done", "artifact": "f3.py"}),
        ("turn.finished", {"outcome": "done", "verdict": "passed", "changed": []}),
    )
    items = plan_items(events)
    assert [item["step"] for item in items] == [1, 2, 3]
    assert [item["state"] for item in items] == ["done", "done", "done"]
    assert [item["verdict"] for item in items] == ["passed", "passed", "passed"]
    assert items[0]["title"] == "edit a" and items[0]["file"] == "f1.py"


def test_a_failure_in_step_two_and_a_skipped_step_three():
    events = _events(
        _plan("edit a", "edit b", "edit c"),
        ("step.started", {"n": 1, "action": "edit a", "target": "f1.py"}),
        ("step.finished", {"n": 1, "outcome": "done", "artifact": "f1.py"}),
        ("step.started", {"n": 2, "action": "edit b", "target": "f2.py"}),
        ("step.finished", {"n": 2, "outcome": "failed", "hint": "tests broke"}),
        ("step.finished", {"n": 3, "outcome": "skipped"}),
        ("turn.finished", {"outcome": "failed", "verdict": "failed", "changed": []}),
    )
    items = plan_items(events)
    assert [item["state"] for item in items] == ["done", "failed", "skipped"]
    assert [item["verdict"] for item in items] == ["passed", "failed", "skipped"]


def test_an_interrupted_step_stays_pending_with_no_verdict():
    events = _events(
        _plan("edit a", "edit b"),
        ("step.started", {"n": 1, "action": "edit a", "target": "f1.py"}),
        ("turn.finished", {"outcome": "interrupted", "verdict": "", "changed": []}),
    )
    items = plan_items(events)
    assert items[0]["state"] == "pending"
    assert items[0]["verdict"] is None


def test_an_ask_mode_run_has_an_empty_plan_array_not_none():
    events = _events(
        ("turn.finished", {"outcome": "done", "verdict": "answered", "changed": []}),
    )
    assert plan_items(events) == []
    result = result_object(events, session="s-1", exit_code=0)
    assert result["plan"] == []


def test_the_result_object_always_carries_the_plan_and_keeps_its_old_fields():
    events = _events(
        _plan("edit a"),
        ("turn.finished", {"outcome": "done", "verdict": "passed", "changed": []}),
    )
    result = result_object(events, session="s-1", exit_code=0)
    assert result["schema"] == "ract.result/1"
    assert result["plan"][0]["step"] == 1
    for old in (
        "outcome",
        "exit_code",
        "session",
        "turns",
        "verdict",
        "final_text",
        "changed",
    ):
        assert old in result


def test_every_string_in_the_plan_is_clean_text():
    events = _events(
        _plan("rewrite \x1b[2J\x07 the module"),
        ("turn.finished", {"outcome": "done", "verdict": "passed", "changed": []}),
    )
    text = json.dumps(plan_items(events))
    assert "\x1b" not in text
    assert "\x07" not in text


def test_the_documented_plan_fields_match_the_coded_ones():
    doc = (ROOT / "docs" / "EVENTS_SESSION.md").read_text(encoding="utf-8")
    row = re.search(r"^\| `plan` \|(.*)$", doc, re.MULTILINE)
    assert row, "docs/EVENTS_SESSION.md has no plan row in the result table"
    documented = set(re.findall(r"`(\w+)`", row.group(1)))
    coded = set(plan_items(_events(_plan("x")))[0])
    assert coded == documented
    assert documented == {"step", "title", "state", "file", "verdict"}
