from __future__ import annotations


import json
from pathlib import Path

from ract.manager import Plan, Step
from ract.plan_replay import PlanReplay, ReplayResult


def _sample_plan() -> Plan:
    return Plan(
        assumption="sample assumption",
        confidence=0.9,
        steps=[
            Step(action="step_one", provider_hint="local", expected_artifact="a.txt"),
            Step(action="step_two", provider_hint="local", expected_artifact="b.txt"),
        ],
    )


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    replay = PlanReplay()
    plan = _sample_plan()
    path = tmp_path / "plan.json"
    replay.save(plan, path)
    loaded = replay.load(path)
    assert loaded.assumption == plan.assumption
    assert loaded.confidence == plan.confidence
    assert len(loaded.steps) == len(plan.steps)
    assert loaded.steps[0].action == "step_one"


def test_replay_success() -> None:
    replay = PlanReplay()
    plan = _sample_plan()
    report = replay.replay(plan, lambda action: f"output:{action}")
    assert report.success is True
    assert len(report.results) == 2
    assert report.results[0].output == "output:step_one"
    assert "succeeded" in report.summary


def test_replay_failure_continues() -> None:
    replay = PlanReplay()
    plan = _sample_plan()

    def executor(action: str) -> str:
        if action == "step_one":
            raise ValueError("boom")
        return "ok"

    report = replay.replay(plan, executor)
    assert report.success is False
    assert report.results[0].success is False
    assert report.results[1].success is True
    assert "failed" in report.summary


def test_verify_determinism_success() -> None:
    replay = PlanReplay()
    plan = _sample_plan()
    deterministic, reports = replay.verify_determinism(
        plan, lambda action: f"out:{action}", trials=3
    )
    assert deterministic is True
    assert len(reports) == 3


def test_verify_determinism_fails_on_unstable_executor() -> None:
    replay = PlanReplay()
    plan = _sample_plan()
    counter = {"n": 0}

    def executor(action: str) -> int:
        counter["n"] += 1
        return counter["n"]

    deterministic, reports = replay.verify_determinism(plan, executor, trials=2)
    assert deterministic is False
    assert len(reports) == 2


def test_result_key_is_serializable() -> None:
    result = ReplayResult(step_index=0, action="a", success=True, output={"x": 1})
    key = PlanReplay._result_key(result)
    assert json.loads(json.dumps(key)) == key


# RACT 0.1.1 - Trust and tooling
