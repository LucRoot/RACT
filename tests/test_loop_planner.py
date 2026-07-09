# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the RACT LoopPlanner."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rootact.loop_planner import LoopPlanner, Milestone
from rootact.manager import Plan, Step
from rootact.rooted import Rooted


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    return tmp_path


def _fake_harness(milestone_json: str) -> MagicMock:
    """Return a mock Harness whose manager returns a Plan with the JSON in assumption."""
    harness = MagicMock()
    plan = Plan(
        assumption=milestone_json,
        confidence=0.9,
        steps=[
            Step(
                action="plan milestones",
                provider_hint="chat",
                expected_artifact="backlog.json",
            )
        ],
    )
    harness.manager.plan.return_value = Rooted(
        value=plan,
        assumption="plan generated",
        confidence=0.9,
    )
    return harness


def test_generate_backlog_parses_milestones(tmp_project: Path):
    planner = LoopPlanner(tmp_project / "rootact.yaml")
    milestone_json = json.dumps(
        {
            "milestones": [
                {
                    "id": "m1",
                    "description": "Implement core",
                    "acceptance": "Core function exists",
                },
                {
                    "id": "m2",
                    "description": "Add tests",
                    "acceptance": "Tests pass",
                },
            ]
        }
    )
    with patch(
        "rootact.loop_planner.Harness.from_config_path",
        return_value=Rooted(
            value=_fake_harness(milestone_json), assumption="ok", confidence=1.0
        ),
    ):
        result = planner.generate_backlog("build a thing")

    assert result.is_ok()
    milestones = result.unwrap()
    assert len(milestones) == 2
    assert milestones[0].id == "m1"
    assert milestones[1].status == "open"


def test_generate_backlog_uses_step_action_as_fallback(tmp_project: Path):
    planner = LoopPlanner(tmp_project / "rootact.yaml")
    milestone_json = json.dumps(
        {
            "milestones": [
                {
                    "id": "a1",
                    "description": "Fallback test",
                    "acceptance": "Fallback works",
                }
            ]
        }
    )
    harness = MagicMock()
    plan = Plan(
        assumption="",
        confidence=0.5,
        steps=[
            Step(
                action=milestone_json,
                provider_hint="chat",
                expected_artifact="backlog.json",
            )
        ],
    )
    harness.manager.plan.return_value = Rooted(
        value=plan,
        assumption="plan generated",
        confidence=0.9,
    )
    with patch(
        "rootact.loop_planner.Harness.from_config_path",
        return_value=Rooted(value=harness, assumption="ok", confidence=1.0),
    ):
        result = planner.generate_backlog("fallback intent")

    assert result.is_ok()
    assert result.unwrap()[0].id == "a1"


def test_generate_backlog_returns_error_on_bad_json(tmp_project: Path):
    planner = LoopPlanner(tmp_project / "rootact.yaml")
    harness = _fake_harness("not json")
    with patch(
        "rootact.loop_planner.Harness.from_config_path",
        return_value=Rooted(value=harness, assumption="ok", confidence=1.0),
    ):
        result = planner.generate_backlog("bad json")

    assert not result.is_ok()
    assert "JSON" in (result.error or "")


def test_save_and_load_roundtrip(tmp_project: Path):
    planner = LoopPlanner(tmp_project / "rootact.yaml")
    milestones = [
        Milestone(id="m1", description="one", acceptance="done"),
        Milestone(id="m2", description="two", acceptance="pending", status="blocked"),
    ]
    path = planner.save(milestones)
    assert path.is_file()

    loaded = planner.load()
    assert loaded is not None
    assert len(loaded) == 2
    assert loaded[0].id == "m1"
    assert loaded[1].status == "blocked"


def test_load_returns_none_when_missing(tmp_project: Path):
    planner = LoopPlanner(tmp_project / "rootact.yaml")
    assert planner.load() is None


def test_next_open_selects_first_open(tmp_project: Path):
    milestones = [
        Milestone(id="m1", description="one", acceptance="done", status="done"),
        Milestone(id="m2", description="two", acceptance="pending"),
        Milestone(id="m3", description="three", acceptance="later"),
    ]
    assert LoopPlanner.next_open(milestones) == milestones[1]


def test_next_open_returns_none_when_all_done(tmp_project: Path):
    milestones = [
        Milestone(id="m1", description="one", acceptance="done", status="done"),
        Milestone(id="m2", description="two", acceptance="done", status="done"),
    ]
    assert LoopPlanner.next_open(milestones) is None


def test_mark_done_updates_status(tmp_project: Path):
    milestones = [
        Milestone(id="m1", description="one", acceptance="done"),
        Milestone(id="m2", description="two", acceptance="pending"),
    ]
    updated = LoopPlanner.mark_done(milestones, "m1")
    assert updated[0].status == "done"
    assert updated[1].status == "open"


def test_mark_done_raises_on_missing_id(tmp_project: Path):
    milestones = [Milestone(id="m1", description="one", acceptance="done")]
    with pytest.raises(KeyError):
        LoopPlanner.mark_done(milestones, "missing")


def test_milestone_validates_status():
    with pytest.raises(ValueError):
        Milestone(id="m1", description="one", acceptance="done", status="invalid")


def test_historian_context_finds_related_symbols(tmp_project: Path):
    (tmp_project / "payment.py").write_text(
        "def process_payment(): pass\n", encoding="utf-8"
    )
    planner = LoopPlanner(tmp_project / "rootact.yaml")
    context = planner._historian_context("payment processing", k=5)
    assert "process_payment" in context


def test_historian_context_returns_empty_when_no_matches(tmp_project: Path):
    planner = LoopPlanner(tmp_project / "rootact.yaml")
    context = planner._historian_context("zzzzzz", k=5)
    assert context == ""


def test_planner_prompt_includes_historian_context(tmp_project: Path):
    planner = LoopPlanner(tmp_project / "rootact.yaml")
    prompt = planner._planner_prompt(
        "build a thing", historian_context="- existing.helper (function)"
    )
    assert "Existing symbols related to this intent" in prompt
    assert "existing.helper" in prompt
    assert "Avoid silent duplication" in prompt


def test_generate_backlog_passes_historian_context_to_planner(tmp_project: Path):
    (tmp_project / "core.py").write_text("def core_helper(): pass\n", encoding="utf-8")
    planner = LoopPlanner(tmp_project / "rootact.yaml")
    milestone_json = json.dumps(
        {
            "milestones": [
                {
                    "id": "m1",
                    "description": "Implement core",
                    "acceptance": "Core function exists",
                }
            ]
        }
    )
    harness = _fake_harness(milestone_json)
    with patch(
        "rootact.loop_planner.Harness.from_config_path",
        return_value=Rooted(value=harness, assumption="ok", confidence=1.0),
    ):
        planner.generate_backlog("build a core helper")

    call_args = harness.manager.plan.call_args
    prompt = call_args[0][0]
    assert "Existing symbols related to this intent" in prompt
    assert "core_helper" in prompt


# RACT 0.1.1 - Trust and tooling
