# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the RunReporter."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from pathlib import Path

from rootact.run_reporter import RunReporter


def test_render_last_loop_when_missing(tmp_path: Path):
    reporter = RunReporter(tmp_path)
    assert "No loop report found" in reporter.render_last_loop()


def test_render_last_loop_shows_summary(tmp_path: Path):
    report_path = tmp_path / ".rootact" / "loop_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "final_decision": "done",
        "summary": "All milestones completed.",
        "handshake_milestones": ["m3"],
        "iterations": [
            {
                "index": 1,
                "decision": "continue",
                "test_returncode": 0,
                "quality_score": 0.9,
                "reflection": "tests passed",
            }
        ],
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    text = RunReporter(tmp_path).render_last_loop()
    assert "Final decision: done" in text
    assert "m3" in text
    assert "tests=pass" in text


def test_render_session_when_missing(tmp_path: Path):
    reporter = RunReporter(tmp_path)
    assert "No session report found" in reporter.render_session("demo")


def test_render_session_shows_outcomes(tmp_path: Path):
    sessions_dir = tmp_path / ".rootact" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "intent": "add feature",
        "plan": {"assumption": "ok", "confidence": 0.9},
        "outcomes": ["write src/foo.py -> src/foo.py"],
    }
    (sessions_dir / "demo.json").write_text(json.dumps(report), encoding="utf-8")
    text = RunReporter(tmp_path).render_session("demo")
    assert "add feature" in text
    assert "write src/foo.py" in text


def test_render_last_loop_json_round_trip(tmp_path: Path):
    report_path = tmp_path / ".rootact" / "loop_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "final_decision": "done",
        "summary": "All milestones completed.",
        "iterations": [{"index": 1, "quality_score": 0.95}],
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    payload = RunReporter(tmp_path).render_last_loop_json()
    assert payload == report


def test_render_session_json_round_trip(tmp_path: Path):
    sessions_dir = tmp_path / ".rootact" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    report = {"intent": "add feature", "outcomes": ["write src/foo.py"]}
    (sessions_dir / "demo.json").write_text(json.dumps(report), encoding="utf-8")
    payload = RunReporter(tmp_path).render_session_json("demo")
    assert payload == report


def test_render_last_loop_json_when_missing(tmp_path: Path):
    assert RunReporter(tmp_path).render_last_loop_json() is None


def test_render_session_json_when_missing(tmp_path: Path):
    assert RunReporter(tmp_path).render_session_json("missing") is None


def test_render_last_loop_includes_metrics(tmp_path: Path):
    report_path = tmp_path / ".rootact" / "loop_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "final_decision": "done",
        "summary": "All done.",
        "handshake_milestones": [],
        "metrics": {
            "total_input_tokens": 100,
            "total_output_tokens": 50,
            "total_tokens": 150,
            "total_cost": 0.0002,
            "total_latency_ms": 42,
        },
        "iterations": [
            {
                "index": 1,
                "decision": "done",
                "test_returncode": 0,
                "quality_score": 0.9,
                "reflection": "tests passed",
                "metrics": {
                    "total_input_tokens": 100,
                    "total_output_tokens": 50,
                    "total_tokens": 150,
                    "total_cost": 0.0002,
                    "total_latency_ms": 42,
                },
            }
        ],
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    text = RunReporter(tmp_path).render_last_loop()
    assert "tokens=150" in text
    assert "cost=0.000200" in text
    assert "latency=42ms" in text


def test_render_last_loop_json_includes_metrics(tmp_path: Path):
    report_path = tmp_path / ".rootact" / "loop_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "final_decision": "done",
        "summary": "All done.",
        "handshake_milestones": [],
        "metrics": {"total_tokens": 10},
        "iterations": [{"index": 1, "metrics": {"total_tokens": 10}}],
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    payload = RunReporter(tmp_path).render_last_loop_json()
    assert payload is not None
    assert payload["metrics"]["total_tokens"] == 10
    assert payload["iterations"][0]["metrics"]["total_tokens"] == 10


def test_render_last_loop_falls_back_to_latest_session(tmp_path: Path):
    sessions_dir = tmp_path / ".rootact" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "intent": "fallback session",
        "plan": {"assumption": "ok", "confidence": 0.9},
        "outcomes": ["write src/bar.py -> src/bar.py"],
    }
    (sessions_dir / "latest.json").write_text(json.dumps(report), encoding="utf-8")
    text = RunReporter(tmp_path).render_last_loop()
    assert "No loop report found" in text
    assert "fallback session" in text
    assert "write src/bar.py" in text


def test_latest_session_id_picks_most_recent(tmp_path: Path):
    sessions_dir = tmp_path / ".rootact" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "older.json").write_text(
        json.dumps({"intent": "old"}), encoding="utf-8"
    )
    (sessions_dir / "newer.json").write_text(
        json.dumps({"intent": "new"}), encoding="utf-8"
    )
    # Ensure distinct mtimes on filesystems that cache quickly.
    import time

    time.sleep(0.01)
    (sessions_dir / "newer.json").touch()
    reporter = RunReporter(tmp_path)
    assert reporter._latest_session_id() == "newer"


# RACT 0.1.1 - Trust and Tooling
