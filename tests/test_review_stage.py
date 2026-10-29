"""B-061c: the review setting, the stage, the events and turn.finished.review (D14)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ract import run_token_budget, turn_context
from ract.config_check import find_config_problems
from ract.review import stage
from ract.rooted import Rooted
from ract.session_events import KINDS
from tests.fixtures.fake_model_server import Scenario
from tests.test_headless import _ract
from tests.test_session_turn import _repo

FIXED = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
OLD = "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n"
FINDINGS = {
    "findings": [
        {
            "path": "src/calc.py",
            "line": 2,
            "severity": "defect",
            "claim": "check the sign",
            "evidence": "return a + b",
        },
        {
            "path": "src/calc.py",
            "line": 90,
            "severity": "defect",
            "claim": "invented",
            "evidence": "nothing",
        },
    ]
}
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


@pytest.mark.parametrize(
    ("config", "expected"),
    [({}, "off"), ({"review": "advisory"}, "advisory"), ({"review": None}, "off")],
)
def test_the_setting(config: dict, expected: str) -> None:
    assert stage.mode(config) == expected


def test_a_wrong_setting_is_a_config_problem() -> None:
    with pytest.raises(stage.ReviewConfigError):
        stage.mode({"review": "always"})
    problems = find_config_problems({"review": "always", "providers": {}})
    assert any("review must be one of" in p for p in problems)


def test_both_events_are_registered() -> None:
    assert {"review.started", "review.finished"} <= KINDS


def test_changed_lines_are_lines_of_the_new_file() -> None:
    assert stage.changed_lines(OLD, FIXED) == {2}
    assert stage.changed_lines(None, "a\nb\n") == {1, 2}


def _events() -> tuple[list[tuple[str, dict]], Any]:
    seen: list[tuple[str, dict]] = []
    return seen, lambda kind, data: seen.append((kind, data))


def _call(tmp_path: Path, complete) -> tuple[dict, list]:
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "calc.py").write_text(FIXED, encoding="utf-8")
    seen, reporter = _events()
    turn_context.bind(turn_context.CancelSignal(), reporter)
    try:
        summary = stage.review_written_step(
            complete,
            root=tmp_path,
            n=1,
            goal="Fix add",
            path="src/calc.py",
            before=OLD,
            after=FIXED,
        )
    finally:
        turn_context.bind(turn_context.CancelSignal(), None)
    return summary, seen


def test_a_review_is_skipped_when_under_20000_tokens_remain(tmp_path: Path) -> None:
    def complete(messages):
        raise AssertionError("no request may be sent")

    with run_token_budget.run_budget(30_000) as budget:
        budget.used = 12_000
        summary, seen = _call(tmp_path, complete)
    assert summary["status"] == "skipped"
    assert "token budget" in summary["note"]
    assert [k for k, _ in seen] == ["review.finished"]


def test_a_review_that_crosses_the_budget_is_stopped_and_its_findings_dropped(
    tmp_path: Path,
) -> None:
    def complete(messages):
        return Rooted(
            value=None,
            assumption="budget",
            confidence=0.0,
            error=f"{run_token_budget.STOP_PREFIX} 50001 tokens; token_budget is 50000.",
        )

    with run_token_budget.run_budget(50_000):
        summary, seen = _call(tmp_path, complete)
    assert summary["status"] == "stopped"
    assert summary["note"] == "review stopped: token budget"
    assert summary["findings"] == []
    assert [k for k, _ in seen] == ["review.started", "review.finished"]


def _run(tmp_path: Path, fake_model_server: Any, review: str | None, *replies: str):
    tmp_path.mkdir(parents=True, exist_ok=True)
    turns = [{"reply": {"kind": "text", "content": c}} for c in (PLAN, FIXED, *replies)]
    turns += [{"reply": {"kind": "text", "content": "Done."}}] * 3
    server = fake_model_server(Scenario.from_dict({"turns": turns}))
    ws = _repo(tmp_path, server.base_url)
    if review is not None:
        config = ws / "ract.yaml"
        config.write_text(
            config.read_text(encoding="utf-8") + f"\nreview: {review}\n",
            encoding="utf-8",
        )
    result = _ract(
        ws, "-p", "fix add", "--accept-edits", "--output-format", "stream-json"
    )
    events = [json.loads(x) for x in result.stdout.splitlines() if x.strip()]
    return ws, result, server, events


def _reviewer_requests(server: Any) -> list[Any]:
    return [
        r for r in server.chat_requests if "You review one step" in json.dumps(r.body)
    ]


def test_review_off_sends_no_review_request(
    tmp_path: Path, fake_model_server: Any
) -> None:
    ws, result, server, events = _run(tmp_path, fake_model_server, None)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _reviewer_requests(server) == []
    finished = [e["data"] for e in events if e["kind"] == "turn.finished"][-1]
    assert finished["review"] is None


def test_the_step_verdict_is_the_verification_result_with_or_without_review(
    tmp_path: Path, fake_model_server: Any
) -> None:
    _, off, _, off_events = _run(tmp_path / "off", fake_model_server, None)
    ws, on, server, on_events = _run(
        tmp_path / "on", fake_model_server, "advisory", json.dumps(FINDINGS)
    )
    assert off.returncode == on.returncode == 0, on.stdout + on.stderr
    assert len(_reviewer_requests(server)) == 1
    finished = [e["data"] for e in on_events if e["kind"] == "turn.finished"][-1]
    off_finished = [e["data"] for e in off_events if e["kind"] == "turn.finished"][-1]
    assert finished["outcome"] == off_finished["outcome"] == "done"
    assert finished["verification"]["status"] == off_finished["verification"]["status"]
    [review] = finished["review"]
    assert review["status"] == "done"
    assert review["reviewer"] == stage.SAME_MODEL
    assert [(f["line"], f["severity"]) for f in review["findings"]] == [(2, "defect")]
    assert review["dropped"] == {"no such line": 1}
    assert (ws / "src" / "calc.py").read_text(encoding="utf-8") == FIXED


def test_model_says_review_off_or_names_the_reviewer() -> None:
    from ract.repl import _review_line

    assert _review_line({}).startswith("review: off")
    assert _review_line({"review": "advisory"}) == "review: advisory (same model)"
    # /model fits a 40-column terminal (tests/test_ux_width.py).
    for config in ({}, {"review": "retry"}, {"review": "bad"}):
        assert len(_review_line(config)) <= 40
