# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the `ract explain` CLI command."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


from ract.cli import _explain_command
from ract.manager import Plan, Step


def test_explain_no_args_prints_help(tmp_path: Path, capsys):
    config_path = tmp_path / "ract.yaml"
    config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
    exit_code = _explain_command(["--config", str(config_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "usage" in captured.out.lower()


def test_explain_from_intent(tmp_path: Path, capsys):
    config_path = tmp_path / "ract.yaml"
    config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
    plan = Plan(
        assumption="add greeting",
        confidence=0.9,
        steps=[
            Step(
                action="write greet.py",
                provider_hint="local",
                expected_artifact="greet.py",
            )
        ],
    )
    mock_result = MagicMock()
    mock_result.is_ok.return_value = True
    mock_result.unwrap.return_value = plan

    with patch("ract.cli.run_ract", return_value=mock_result):
        exit_code = _explain_command(
            ["--intent", "add a greeting", "--config", str(config_path)]
        )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "RACT Plan Explanation" in captured.out
    assert "add greeting" in captured.out
    assert "write greet.py" in captured.out
    assert "greet.py" in captured.out


def test_explain_planning_failure(tmp_path: Path, capsys):
    config_path = tmp_path / "ract.yaml"
    config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
    mock_result = MagicMock()
    mock_result.is_ok.return_value = False
    mock_result.error = "provider unreachable"

    with patch("ract.cli.run_ract", return_value=mock_result):
        exit_code = _explain_command(
            ["--intent", "add a greeting", "--config", str(config_path)]
        )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "provider unreachable" in captured.err


def test_explain_from_plan_file(tmp_path: Path, capsys):
    config_path = tmp_path / "ract.yaml"
    config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "assumption": "refactor",
                "confidence": 0.8,
                "steps": [
                    {
                        "action": "rename foo to bar",
                        "provider_hint": "local",
                        "expected_artifact": "src/bar.py",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = _explain_command(
        ["--plan", str(plan_path), "--config", str(config_path)]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "refactor" in captured.out
    assert "rename foo to bar" in captured.out
    assert "src/bar.py" in captured.out


def test_explain_missing_plan_file(tmp_path: Path, capsys):
    config_path = tmp_path / "ract.yaml"
    config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
    missing = tmp_path / "missing.json"
    exit_code = _explain_command(["--plan", str(missing), "--config", str(config_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "failed to load plan" in captured.err


# RACT 0.1.1 - Trust and tooling
