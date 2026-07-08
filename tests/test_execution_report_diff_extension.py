# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from rootact.execution_report_diff_extension import DiffExtension
from rootact.executor import ExecutionReport, StepResult
from rootact.manager import Step

_ROOT_KNOT = object()


def _make_report(step_results: list[StepResult]) -> ExecutionReport:
    return ExecutionReport(
        intent="test intent",
        step_results=step_results,
        assumptions=["test assumption"],
        provenance={"run_id": "abc"},
        artifacts={"extra": "value"},
    )


def test_attach_diff_summary_enriches_artifacts() -> None:
    step = Step(action="write", provider_hint="code", expected_artifact="src/foo.py")
    result = StepResult(step=step, raw_response={}, content="print('hello')")
    report = _make_report([result])

    enriched = DiffExtension().attach_diff_summary(report)

    assert enriched.artifacts["change_summary"] != ""
    assert "added 1 file(s)" in enriched.artifacts["change_summary"]
    assert enriched.artifacts["file_diff"] != ""
    assert "src/foo.py" in enriched.artifacts["file_diff"]
    # Original artifacts and fields must be preserved.
    assert enriched.artifacts["extra"] == "value"
    assert enriched.intent == report.intent
    assert enriched.step_results == report.step_results
    assert enriched.assumptions == report.assumptions
    assert enriched.provenance == report.provenance


def test_attach_diff_summary_no_steps() -> None:
    report = _make_report([])

    enriched = DiffExtension().attach_diff_summary(report)

    assert enriched.artifacts["change_summary"] != ""
    assert enriched.artifacts["file_diff"] != ""
    assert enriched.artifacts["extra"] == "value"
