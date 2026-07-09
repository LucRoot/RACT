# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the coverage-delta gate and its wiring into Harness.run."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from unittest.mock import MagicMock

import pytest

from rootact import coverage_delta
from rootact.executor import ExecutionReport, StepResult
from rootact.harness import Harness
from rootact.manager import Plan, Step
from rootact.rooted import Rooted


@pytest.fixture
def tmp_coverage_project(tmp_path_factory):
    """Build a minimal project that pytest-cov can measure."""
    project_dir = tmp_path_factory.mktemp("cov_project")
    src = project_dir / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "core.py").write_text(
        "def branch(value: bool) -> int:\n"
        "    if value:\n"
        "        return 1\n"
        "    return 2\n",
        encoding="utf-8",
    )
    tests = project_dir / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_core.py").write_text(
        "from pkg.core import branch\n\n"
        "def test_true_branch():\n"
        "    assert branch(True) == 1\n",
        encoding="utf-8",
    )
    (project_dir / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
        'pythonpath = ["src"]\n'
        'addopts = "--cov=pkg --cov-report=term-missing"\n',
        encoding="utf-8",
    )
    return project_dir


def test_gate_establishes_baseline(tmp_coverage_project):
    project_dir = tmp_coverage_project
    result = coverage_delta.gate(
        project_dir, pytest_args=["tests/", "-q"], timeout=60.0
    )
    assert result.is_ok(), result.error
    delta = result.unwrap()
    assert delta.verdict == "baseline"
    assert (project_dir / ".rootact" / "coverage_baseline.json").exists()


def test_gate_detects_regress(tmp_coverage_project):
    project_dir = tmp_coverage_project
    coverage_delta.gate(project_dir, pytest_args=["tests/", "-q"], timeout=60.0)

    # Add an uncovered function.
    core_path = project_dir / "src" / "pkg" / "core.py"
    core_path.write_text(
        core_path.read_text(encoding="utf-8")
        + "\ndef uncovered() -> int:\n    return 2\n",
        encoding="utf-8",
    )

    result = coverage_delta.gate(
        project_dir, pytest_args=["tests/", "-q"], timeout=60.0
    )
    assert result.is_ok(), result.error
    delta = result.unwrap()
    assert delta.verdict == "regress"
    assert delta.percent_delta < 0


def test_gate_detects_earn(tmp_coverage_project):
    project_dir = tmp_coverage_project
    coverage_delta.gate(project_dir, pytest_args=["tests/", "-q"], timeout=60.0)

    # Cover the missing branch.
    test_path = project_dir / "tests" / "test_core.py"
    test_path.write_text(
        test_path.read_text(encoding="utf-8")
        + "\ndef test_false_branch():\n    assert branch(False) == 2\n",
        encoding="utf-8",
    )

    result = coverage_delta.gate(
        project_dir, pytest_args=["tests/", "-q"], timeout=60.0
    )
    assert result.is_ok(), result.error
    delta = result.unwrap()
    assert delta.verdict == "earn"
    assert delta.percent_delta > 0


def test_harness_hard_fail_on_coverage_regress(tmp_path, monkeypatch):
    """Coverage gate hard_fail returns a Rooted error when the verdict regresses."""
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
        "coverage_gate": {
            "enabled": True,
            "hard_fail": True,
            "timeout": 60.0,
        },
    }
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "manager.txt").write_text(
        "You are the manager.", encoding="utf-8"
    )
    config_path = tmp_path / "rootact.yaml"
    import yaml

    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()

    fake_plan = Plan(
        assumption="test plan",
        confidence=1.0,
        steps=[Step(action="noop", provider_hint="chat", expected_artifact="out.txt")],
    )
    harness.planner.plan = MagicMock(
        return_value=Rooted(value=fake_plan, assumption="ok", confidence=1.0)
    )
    fake_report = ExecutionReport(
        intent="noop",
        step_results=[
            StepResult(
                step=fake_plan.steps[0],
                raw_response={},
                content="",
            )
        ],
        assumptions=[],
    )
    harness.executor.execute = MagicMock(
        return_value=Rooted(value=fake_report, assumption="ok", confidence=1.0)
    )

    before = coverage_delta.CoverageSnapshot(
        percent_covered=95.0,
        covered_lines=95,
        missing_lines=5,
        total_lines=100,
    )
    after = coverage_delta.CoverageSnapshot(
        percent_covered=90.0,
        covered_lines=90,
        missing_lines=10,
        total_lines=100,
    )
    monkeypatch.setattr(
        "rootact.harness.coverage_gate",
        lambda *_args, **_kwargs: Rooted(
            value=coverage_delta.compute_delta(before, after),
            assumption="ok",
            confidence=1.0,
        ),
    )

    result = harness.run("noop")
    assert not result.is_ok()
    assert "Coverage gate" in (result.error or "")
    assert "regress" in (result.error or "")


def test_harness_soft_fail_attaches_delta(tmp_path, monkeypatch):
    """Coverage gate soft_fail attaches the delta to the report artifacts."""
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
        "coverage_gate": {
            "enabled": True,
            "hard_fail": False,
            "timeout": 60.0,
        },
    }
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "manager.txt").write_text(
        "You are the manager.", encoding="utf-8"
    )
    config_path = tmp_path / "rootact.yaml"
    import yaml

    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()

    fake_plan = Plan(
        assumption="test plan",
        confidence=1.0,
        steps=[Step(action="noop", provider_hint="chat", expected_artifact="out.txt")],
    )
    harness.planner.plan = MagicMock(
        return_value=Rooted(value=fake_plan, assumption="ok", confidence=1.0)
    )
    fake_report = ExecutionReport(
        intent="noop",
        step_results=[
            StepResult(
                step=fake_plan.steps[0],
                raw_response={},
                content="",
            )
        ],
        assumptions=[],
    )
    harness.executor.execute = MagicMock(
        return_value=Rooted(value=fake_report, assumption="ok", confidence=1.0)
    )

    before = coverage_delta.CoverageSnapshot(
        percent_covered=94.0,
        covered_lines=94,
        missing_lines=6,
        total_lines=100,
    )
    after = coverage_delta.CoverageSnapshot(
        percent_covered=94.0,
        covered_lines=188,
        missing_lines=12,
        total_lines=200,
    )
    monkeypatch.setattr(
        "rootact.harness.coverage_gate",
        lambda *_args, **_kwargs: Rooted(
            value=coverage_delta.compute_delta(before, after),
            assumption="ok",
            confidence=1.0,
        ),
    )

    result = harness.run("noop")
    assert result.is_ok(), result.error
    report = result.unwrap()
    assert "coverage_delta" in report.artifacts
    assert report.artifacts["coverage_delta"]["verdict"] == "stagnant"


def test_harness_floor_breach_hard_fail(tmp_path, monkeypatch):
    """Coverage gate hard_fail returns a Rooted error when the floor is breached."""
    config = {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
        "coverage_gate": {
            "enabled": True,
            "hard_fail": True,
            "timeout": 60.0,
            "min_percent": 95.0,
        },
    }
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "manager.txt").write_text(
        "You are the manager.", encoding="utf-8"
    )
    config_path = tmp_path / "rootact.yaml"
    import yaml

    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    harness_rooted = Harness.from_config_path(config_path)
    assert harness_rooted.is_ok(), harness_rooted.error
    harness = harness_rooted.unwrap()

    fake_plan = Plan(
        assumption="test plan",
        confidence=1.0,
        steps=[Step(action="noop", provider_hint="chat", expected_artifact="out.txt")],
    )
    harness.planner.plan = MagicMock(
        return_value=Rooted(value=fake_plan, assumption="ok", confidence=1.0)
    )
    fake_report = ExecutionReport(
        intent="noop",
        step_results=[
            StepResult(
                step=fake_plan.steps[0],
                raw_response={},
                content="",
            )
        ],
        assumptions=[],
    )
    harness.executor.execute = MagicMock(
        return_value=Rooted(value=fake_report, assumption="ok", confidence=1.0)
    )

    before = coverage_delta.CoverageSnapshot(
        percent_covered=96.0,
        covered_lines=96,
        missing_lines=4,
        total_lines=100,
    )
    after = coverage_delta.CoverageSnapshot(
        percent_covered=92.0,
        covered_lines=92,
        missing_lines=8,
        total_lines=100,
    )

    def _fake_gate(_project_dir, *, min_percent=None, **kwargs):
        return Rooted(
            value=coverage_delta.compute_delta(before, after, min_percent=min_percent),
            assumption="ok",
            confidence=1.0,
        )

    monkeypatch.setattr("rootact.harness.coverage_gate", _fake_gate)

    result = harness.run("noop")
    assert not result.is_ok()
    assert "Coverage gate" in (result.error or "")
    assert "Floor breached" in (result.error or "")


# RACT 0.1.1 - Trust and tooling
