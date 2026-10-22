"""B-038: the turn summary is the harness's account, not the model's."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ract.session_events import EventStream
from ract.session_render import PlainRenderer
from ract.turn_summary import describe_change, diffstat, unverified_claims
from tests.fixtures.fake_model_server import Scenario
from tests.test_headless import _ract
from tests.test_session_turn import FIXED, _repo


# ------------------------------------------------------------------ claims


@pytest.mark.parametrize(
    ("text", "claims"),
    [
        ("Fixed add(). All tests pass now.", ["tests pass"]),
        ("The change passes all 6 tests.", ["tests pass"]),
        ("I verified that the loader reads ract.yaml.", ["verified"]),
        ("Done and tested.", ["tested"]),
    ],
)
def test_claims_a_verifier_would_have_to_back(text: str, claims: list[str]) -> None:
    assert unverified_claims(text) == claims


@pytest.mark.parametrize(
    "text",
    [
        "Run pytest to check that the tests pass.",
        "Keep going until the tests pass.",
        "The tests do not pass yet: add() still subtracts.",
        "If the tests pass, commit the change.",
        "You should make sure tests pass before merging.",
        "The config loader is load_config in src/app/config.py.",
    ],
)
def test_instructions_conditions_and_negations_are_not_claims(text: str) -> None:
    assert unverified_claims(text) == []


# ---------------------------------------------------------------- diffstat


def test_diffstat_counts_only_what_the_turn_changed(tmp_path: Path) -> None:
    # G-059: from the turn's backup, not git HEAD, and with no git at all.
    project = tmp_path / "project"  # not a git repository
    before = tmp_path / "backup"
    project.mkdir()
    before.mkdir()
    # The operator had already edited a.py (two uncommitted lines) before
    # the turn; the turn then changed one more line.
    (before / "a.py").write_text("one\nmine 1\nmine 2\n", encoding="utf-8")
    (project / "a.py").write_text("ONE\nmine 1\nmine 2\n", encoding="utf-8")
    (before / "gone.py").write_text("x\ny\n", encoding="utf-8")
    (project / "new.md").write_text("a\nb\nc\n", encoding="utf-8")
    (project / "logo.bin").write_bytes(b"\xff\xfe\x00")

    stats = diffstat(
        project,
        ["a.py", "new.md", "gone.py", "logo.bin"],
        before,
        {"a.py", "gone.py"},
    )

    assert stats["a.py"] == {"added": 1, "removed": 1}
    assert stats["new.md"] == {"new": 3}
    assert stats["gone.py"] == {"deleted": True}
    assert stats["logo.bin"] == {"binary": True}
    assert describe_change("a.py", stats["a.py"]) == "a.py (+1 -1)"
    assert describe_change("new.md", stats["new.md"]) == "new.md (new, 3 lines)"
    assert diffstat(project, [], before, set()) == {}


# ----------------------------------------------------------------- render


def _render(events: list[tuple[str, dict[str, Any]]]) -> str:
    out: list[str] = []
    stream = EventStream(session="s")
    stream.subscribe(PlainRenderer(out.append))
    for kind, data in events:
        stream.emit(kind, data, turn=1)
    return "".join(out)


FINISHED = {
    "outcome": "done",
    "duration_ms": 3200,
    "verdict": "Done: 1 step ran; no tests were run.",
    "workspace": "1 file changed",
    "changed": ["src/calc.py"],
    "diffstat": {"src/calc.py": {"added": 1, "removed": 1}},
    "undo": ".ract/undo/20261022T000000Z-abc123/",
    "checkpoint": None,
    "verification": {"status": "not-run", "runs": [], "claims": ["tests pass"]},
    "provenance": {"signed": False, "unsigned_files": ["src/calc.py"]},
}


def test_the_summary_is_assembled_from_events() -> None:
    text = _render(
        [
            ("turn.started", {"input": "fix add", "queued": False}),
            (
                "plan.proposed",
                {"assumption": "add() subtracts", "confidence": 0.85, "steps": []},
            ),
            (
                "cost.updated",
                {"tokens_in": 1068, "tokens_out": 85, "requests": 2, "by_purpose": {}},
            ),
            ("turn.finished", FINISHED),
        ]
    )

    assert "  Done: 1 step ran; no tests were run.\n" in text
    assert "  changed: src/calc.py (+1 -1); unstaged, review with git diff\n" in text
    assert (
        "  way back: previous versions in .ract/undo/20261022T000000Z-abc123/\n" in text
    )
    assert "  verified: RACT ran no tests this turn\n" in text
    assert '  the reply says "tests pass"; nothing in this turn checked that\n' in text
    assert "  assumed: add() subtracts (planner confidence 0.85, not checked)\n" in text
    assert "  2 model requests, 3.2 s, 1068 tokens in / 85 out\n" in text


def test_a_turn_that_changed_nothing_has_a_short_summary() -> None:
    finished = dict(FINISHED, changed=[], diffstat={}, undo=None)
    finished["verification"] = {"status": "not-run", "runs": [], "claims": []}
    finished["provenance"] = {"signed": False, "unsigned_files": []}
    text = _render(
        [
            (
                "plan.proposed",
                {"assumption": "a question", "confidence": 0.9, "steps": []},
            ),
            (
                "cost.updated",
                {
                    "tokens_in": None,
                    "tokens_out": None,
                    "requests": 1,
                    "by_purpose": {},
                },
            ),
            ("turn.finished", finished),
        ]
    )

    assert "  changed: nothing\n" in text
    assert "way back" not in text and "assumed:" not in text and "unsigned" not in text
    assert "  1 model request, 3.2 s, tokens not reported\n" in text


def test_prose_after_a_file_change_is_labelled_model_summary() -> None:
    text = _render(
        [
            ("turn.started", {"input": "fix", "queued": False}),
            (
                "step.finished",
                {
                    "n": 1,
                    "outcome": "done",
                    "artifact": "src/calc.py",
                    "duration_ms": 1,
                },
            ),
            ("agent.text.delta", {"text": "I fixed add.", "channel": "answer"}),
        ]
    )

    assert "model summary:\nI fixed add." in text


# ------------------------------------------------------------- end to end


def test_a_real_turn_reports_diffstat_and_an_unverified_claim(
    tmp_path: Path, fake_model_server: Any
) -> None:
    plan = json.dumps(
        {
            "assumption": "add() subtracts",
            "confidence": 0.85,
            "steps": [
                {
                    "action": "Fix add",
                    "provider_hint": "local",
                    "expected_artifact": "src/calc.py",
                },
                {
                    "action": "Report what changed",
                    "provider_hint": "local",
                    "expected_artifact": "",
                },
            ],
        }
    )
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {"reply": {"kind": "text", "content": plan}},
                    {"reply": {"kind": "text", "content": FIXED}},
                    {
                        "reply": {
                            "kind": "text",
                            "content": "Fixed add(). All tests pass now.",
                        }
                    },
                ]
            }
        )
    )
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "fix add", "--output-format", "stream-json")

    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    finished = [e["data"] for e in events if e["kind"] == "turn.finished"][-1]
    assert finished["diffstat"] == {"src/calc.py": {"added": 1, "removed": 1}}
    assert finished["verification"]["claims"] == ["tests pass"]
    assert finished["undo"] and finished["undo"].startswith(".ract/undo/")
    assert '"tests pass"; nothing in this turn checked that' in result.stderr


def test_the_old_one_line_summary_is_gone() -> None:
    text = _render([("turn.finished", FINISHED)])
    assert " | " not in text
