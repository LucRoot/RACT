# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the mutation-score gate and its wiring into Harness.run."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from unittest.mock import MagicMock

import yaml

from ract.executor import ExecutionReport, StepResult
from ract.harness import Harness
from ract.manager import Plan, Step
from ract.mutation_runner import MutationReport
from ract.rooted import Rooted


def _make_harness_config(mutation_gate_cfg):
    return {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
        "mutation_gate": mutation_gate_cfg,
    }


def _bootstrap_harness(tmp_path, config):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "manager.txt").write_text(
        "You are the manager.", encoding="utf-8"
    )
    config_path = tmp_path / "ract.yaml"
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
    return harness, fake_report


def test_harness_mutation_gate_disabled_by_default(tmp_path, monkeypatch):
    """When mutation_gate is absent from config, the gate does not run."""
    config = _make_harness_config({})
    harness, _fake_report = _bootstrap_harness(tmp_path, config)

    called = []
    monkeypatch.setattr(
        "ract.harness.run_mutation_tests",
        lambda *_args, **_kwargs: (
            called.append(True)
            or Rooted(
                value=MutationReport(killed=50, survived=50, timeout=0, error=0),
                assumption="ok",
                confidence=1.0,
            )
        ),
    )

    result = harness.run("noop")
    assert result.is_ok(), result.error
    assert not called


def test_harness_mutation_gate_hard_fail_on_low_score(tmp_path, monkeypatch):
    """Mutation gate hard_fail returns a Rooted error when score is below floor."""
    config = _make_harness_config(
        {"enabled": True, "hard_fail": True, "min_score": 90.0, "timeout": 60.0}
    )
    harness, _fake_report = _bootstrap_harness(tmp_path, config)

    monkeypatch.setattr(
        "ract.harness.run_mutation_tests",
        lambda *_args, **_kwargs: Rooted(
            value=MutationReport(killed=70, survived=30, timeout=0, error=0),
            assumption="ok",
            confidence=1.0,
        ),
    )

    result = harness.run("noop")
    assert not result.is_ok()
    assert "Mutation gate" in (result.error or "")
    assert "70.00%" in (result.error or "")
    assert "90.00%" in (result.error or "")


def test_harness_mutation_gate_soft_fail_attaches_artifact(tmp_path, monkeypatch):
    """Mutation gate soft_fail attaches the score to report artifacts."""
    config = _make_harness_config(
        {"enabled": True, "hard_fail": False, "min_score": 90.0, "timeout": 60.0}
    )
    harness, _fake_report = _bootstrap_harness(tmp_path, config)

    monkeypatch.setattr(
        "ract.harness.run_mutation_tests",
        lambda *_args, **_kwargs: Rooted(
            value=MutationReport(killed=70, survived=30, timeout=0, error=0),
            assumption="ok",
            confidence=1.0,
        ),
    )

    result = harness.run("noop")
    assert result.is_ok(), result.error
    report = result.unwrap()
    assert "mutation_score" in report.artifacts
    artifact = report.artifacts["mutation_score"]
    assert artifact["score"] == 70.0
    assert artifact["killed"] == 70
    assert artifact["survived"] == 30
    assert artifact["min_score"] == 90.0


def test_harness_mutation_gate_pass_attaches_artifact(tmp_path, monkeypatch):
    """Mutation gate records the artifact even when the score passes."""
    config = _make_harness_config(
        {"enabled": True, "hard_fail": True, "min_score": 50.0, "timeout": 60.0}
    )
    harness, _fake_report = _bootstrap_harness(tmp_path, config)

    monkeypatch.setattr(
        "ract.harness.run_mutation_tests",
        lambda *_args, **_kwargs: Rooted(
            value=MutationReport(killed=80, survived=20, timeout=0, error=0),
            assumption="ok",
            confidence=1.0,
        ),
    )

    result = harness.run("noop")
    assert result.is_ok(), result.error
    report = result.unwrap()
    assert report.artifacts["mutation_score"]["score"] == 80.0


def test_harness_mutation_gate_run_error_hard_fail(tmp_path, monkeypatch):
    """Mutation gate hard_fail surfaces runner errors."""
    config = _make_harness_config(
        {"enabled": True, "hard_fail": True, "min_score": 80.0, "timeout": 60.0}
    )
    harness, _fake_report = _bootstrap_harness(tmp_path, config)

    monkeypatch.setattr(
        "ract.harness.run_mutation_tests",
        lambda *_args, **_kwargs: Rooted(
            value=None,
            assumption="script exists",
            confidence=0.0,
            error="WSL not available",
        ),
    )

    result = harness.run("noop")
    assert not result.is_ok()
    assert "Mutation gate error" in (result.error or "")
    assert "WSL not available" in (result.error or "")


def test_harness_mutation_gate_run_error_soft_fail(tmp_path, monkeypatch):
    """Mutation gate soft_fail ignores runner errors and continues."""
    config = _make_harness_config(
        {"enabled": True, "hard_fail": False, "min_score": 80.0, "timeout": 60.0}
    )
    harness, _fake_report = _bootstrap_harness(tmp_path, config)

    monkeypatch.setattr(
        "ract.harness.run_mutation_tests",
        lambda *_args, **_kwargs: Rooted(
            value=None,
            assumption="script exists",
            confidence=0.0,
            error="WSL not available",
        ),
    )

    result = harness.run("noop")
    assert result.is_ok(), result.error
    report = result.unwrap()
    assert "mutation_score" not in report.artifacts


# RACT 0.1.1 - Trust and tooling
