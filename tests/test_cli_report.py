# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the `rootact report` CLI command."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from pathlib import Path

from rootact.cli import _report_command


def _write_loop_report(tmp_path: Path, report: dict) -> None:
    report_path = tmp_path / ".rootact" / "loop_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report), encoding="utf-8")


def test_report_last_text_format(tmp_path: Path, capsys):
    _write_loop_report(tmp_path, {"final_decision": "done", "summary": "ok"})
    exit_code = _report_command(["--last", "--config", str(tmp_path / "rootact.yaml")])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "RACT Loop Report" in captured.out
    assert "done" in captured.out


def test_report_last_json_format(tmp_path: Path, capsys):
    _write_loop_report(tmp_path, {"final_decision": "done", "summary": "ok"})
    exit_code = _report_command(
        ["--last", "--format", "json", "--config", str(tmp_path / "rootact.yaml")]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["final_decision"] == "done"


def test_report_last_json_output_file(tmp_path: Path):
    _write_loop_report(tmp_path, {"final_decision": "done", "summary": "ok"})
    output_path = tmp_path / "report.json"
    exit_code = _report_command(
        [
            "--last",
            "--format",
            "json",
            "--output",
            str(output_path),
            "--config",
            str(tmp_path / "rootact.yaml"),
        ]
    )
    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["summary"] == "ok"


def test_report_session_json_format(tmp_path: Path, capsys):
    sessions_dir = tmp_path / ".rootact" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    report = {"intent": "add feature", "outcomes": ["write src/foo.py"]}
    (sessions_dir / "demo.json").write_text(json.dumps(report), encoding="utf-8")
    exit_code = _report_command(
        [
            "--session",
            "demo",
            "--format",
            "json",
            "--config",
            str(tmp_path / "rootact.yaml"),
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["intent"] == "add feature"


def test_report_missing_loop_json_is_empty_object(tmp_path: Path, capsys):
    exit_code = _report_command(
        ["--last", "--format", "json", "--config", str(tmp_path / "rootact.yaml")]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "{}"


# RACT 0.1.1 - Trust and tooling
