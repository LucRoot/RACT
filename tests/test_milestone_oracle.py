# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the Milestone Oracle."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

from rootact.executor import ExecutionReport, StepResult
from rootact.loop_planner import Milestone
from rootact.manager import Plan, Step
from rootact.milestone_oracle import MilestoneContext, MilestoneOracle


def _make_report(artifacts: dict[str, str], project_dir: Path) -> ExecutionReport:
    step_results = []
    for name, content in artifacts.items():
        step = Step(
            action=f"write {name}", provider_hint="chat", expected_artifact=name
        )
        path = project_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        step_results.append(StepResult(step=step, raw_response={}, content=content))
    return ExecutionReport(
        intent="test",
        step_results=step_results,
        assumptions=["ok"],
        provenance={},
        artifacts={},
        plan=Plan(
            assumption="ok", confidence=0.9, steps=[sr.step for sr in step_results]
        ),
    )


def test_oracle_retries_when_tests_fail(tmp_path: Path):
    oracle = MilestoneOracle()
    milestone = Milestone(id="m1", description="core", acceptance="works")
    report = _make_report({"src/foo.py": "# code\n"}, tmp_path)
    context = MilestoneContext(
        milestone=milestone,
        report=report,
        test_returncode=1,
        project_dir=tmp_path,
    )
    result = oracle.evaluate({"milestone_context": context})
    assert result.is_ok()
    assert result.unwrap().verdict == "retry"


def test_oracle_proceeds_when_criteria_met(tmp_path: Path):
    oracle = MilestoneOracle()
    milestone = Milestone(id="m1", description="core", acceptance="produce src/foo.py")
    report = _make_report({"src/foo.py": "# code\n"}, tmp_path)
    context = MilestoneContext(
        milestone=milestone,
        report=report,
        test_returncode=0,
        project_dir=tmp_path,
    )
    result = oracle.evaluate({"milestone_context": context})
    assert result.is_ok()
    assert result.unwrap().verdict == "proceed"


def test_oracle_retries_when_test_file_missing(tmp_path: Path):
    oracle = MilestoneOracle()
    milestone = Milestone(id="m1", description="tests", acceptance="add tests")
    report = _make_report({"src/foo.py": "# code\n"}, tmp_path)
    context = MilestoneContext(
        milestone=milestone,
        report=report,
        test_returncode=0,
        project_dir=tmp_path,
    )
    result = oracle.evaluate({"milestone_context": context})
    assert result.is_ok()
    assert result.unwrap().verdict == "retry"


def test_oracle_allows_when_test_file_present(tmp_path: Path):
    oracle = MilestoneOracle()
    milestone = Milestone(id="m1", description="tests", acceptance="add tests")
    report = _make_report({"tests/test_foo.py": "def test_foo(): pass\n"}, tmp_path)
    context = MilestoneContext(
        milestone=milestone,
        report=report,
        test_returncode=0,
        project_dir=tmp_path,
    )
    result = oracle.evaluate({"milestone_context": context})
    assert result.is_ok()
    assert result.unwrap().verdict == "proceed"


def test_oracle_handshakes_high_risk_milestone(tmp_path: Path):
    oracle = MilestoneOracle()
    milestone = Milestone(
        id="m1", description="deploy", acceptance="push to production"
    )
    report = _make_report({"src/foo.py": "# code\n"}, tmp_path)
    context = MilestoneContext(
        milestone=milestone,
        report=report,
        test_returncode=0,
        project_dir=tmp_path,
    )
    result = oracle.evaluate({"milestone_context": context})
    assert result.is_ok()
    assert result.unwrap().verdict == "handshake"


def test_oracle_fails_on_missing_context():
    oracle = MilestoneOracle()
    result = oracle.evaluate({})
    assert not result.is_ok()


def test_oracle_retries_when_report_is_none(tmp_path: Path):
    oracle = MilestoneOracle()
    milestone = Milestone(id="m1", description="core", acceptance="works")
    context = MilestoneContext(
        milestone=milestone,
        report=None,
        test_returncode=0,
        project_dir=tmp_path,
    )
    result = oracle.evaluate({"milestone_context": context})
    assert result.is_ok()
    assert result.unwrap().verdict == "retry"


def test_oracle_retries_when_file_hint_missing(tmp_path: Path):
    oracle = MilestoneOracle()
    milestone = Milestone(
        id="m1", description="core", acceptance="produce src/missing.py"
    )
    report = _make_report({"src/foo.py": "# code\n"}, tmp_path)
    context = MilestoneContext(
        milestone=milestone,
        report=report,
        test_returncode=0,
        project_dir=tmp_path,
    )
    result = oracle.evaluate({"milestone_context": context})
    assert result.is_ok()
    assert result.unwrap().verdict == "retry"


def test_oracle_retries_when_symbol_hint_missing(tmp_path: Path):
    oracle = MilestoneOracle()
    milestone = Milestone(
        id="m1", description="core", acceptance="define function helper"
    )
    report = _make_report({"src/foo.py": "# code\n"}, tmp_path)
    context = MilestoneContext(
        milestone=milestone,
        report=report,
        test_returncode=0,
        project_dir=tmp_path,
    )
    result = oracle.evaluate({"milestone_context": context})
    assert result.is_ok()
    assert result.unwrap().verdict == "retry"


def test_oracle_symbol_present_in_artifact(tmp_path: Path):
    oracle = MilestoneOracle()
    milestone = Milestone(
        id="m1", description="core", acceptance="define function helper"
    )
    report = _make_report({"src/foo.py": "def helper(): pass\n"}, tmp_path)
    context = MilestoneContext(
        milestone=milestone,
        report=report,
        test_returncode=0,
        project_dir=tmp_path,
    )
    result = oracle.evaluate({"milestone_context": context})
    assert result.is_ok()
    assert result.unwrap().verdict == "proceed"


def test_oracle_evaluates_with_plan_report(tmp_path: Path):
    oracle = MilestoneOracle()
    milestone = Milestone(id="m1", description="core", acceptance="works")
    plan = Plan(assumption="ok", confidence=0.9, steps=[])
    context = MilestoneContext(
        milestone=milestone,
        report=plan,
        test_returncode=0,
        project_dir=tmp_path,
    )
    result = oracle.evaluate({"milestone_context": context})
    assert result.is_ok()
    assert result.unwrap().verdict == "proceed"


# RACT 0.1.1 - Trust and Tooling
