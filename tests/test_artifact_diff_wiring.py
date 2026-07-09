# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.artifact_diff_wiring import render_change_summary, render_file_diff
from rootact.executor import ExecutionReport, StepResult
from rootact.manager import Plan, Step


def _make_report(contents: dict[str, str]) -> ExecutionReport:
    plan = Plan(
        assumption="test plan",
        confidence=0.9,
        steps=[
            Step(action=f"create {name}", provider_hint="test", expected_artifact=name)
            for name in contents
        ],
    )
    step_results = [
        StepResult(
            step=Step(
                action=f"create {name}", provider_hint="test", expected_artifact=name
            ),
            raw_response={},
            content=content,
        )
        for name, content in contents.items()
    ]
    return ExecutionReport(
        intent="test intent",
        step_results=step_results,
        assumptions=[plan.assumption],
    )


def test_render_change_summary_lists_added_files():
    report = _make_report({"a.txt": "hello", "b.txt": "world"})
    summary = render_change_summary(report)
    assert "added 2 file(s)" in summary


def test_render_change_summary_detects_no_changes():
    report = _make_report({})
    summary = render_change_summary(report)
    assert summary == "No changes detected."


def test_render_file_diff_shows_added_file():
    diff = render_file_diff({}, {"a.txt": "hello"})
    assert "Added:" in diff
    assert "a.txt" in diff


def test_render_file_diff_shows_changed_file():
    diff = render_file_diff({"a.txt": "hello"}, {"a.txt": "hello world"})
    assert "--- a.txt" in diff or "+++ a.txt" in diff or "hello world" in diff


def test_render_file_diff_reports_no_changes_when_equal():
    diff = render_file_diff({"a.txt": "hello"}, {"a.txt": "hello"})
    assert diff == "No changes detected."


# RACT 0.1.1 - Trust and tooling
