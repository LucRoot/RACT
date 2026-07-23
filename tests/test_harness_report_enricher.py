# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from unittest.mock import MagicMock

from ract.executor import ExecutionReport, StepResult
from ract.harness import Harness
from ract.harness_report_enricher import enrich_harness_run
from ract.manager import Step
from ract.rooted import Rooted

_ROOT_KNOT = object()


def _make_harness(
    report: ExecutionReport | None = None, error: str | None = None
) -> Harness:
    harness = MagicMock(spec=Harness)
    if error is not None:
        harness.run.return_value = Rooted(value=None, error=error)
    elif report is not None:
        harness.run.return_value = Rooted(
            value=report,
            assumption="plan executed",
            confidence=0.95,
            provenance=["manager", "executor"],
        )
    else:
        harness.run.return_value = Rooted(value=None, error="no report")
    return harness


def _make_report(content: str = "print('hello')") -> ExecutionReport:
    step = Step(action="write", provider_hint="code", expected_artifact="src/foo.py")
    result = StepResult(step=step, raw_response={}, content=content)
    return ExecutionReport(
        intent="test intent",
        step_results=[result],
        assumptions=["test assumption"],
        provenance={"run_id": "abc"},
        artifacts={"extra": "value"},
    )


def test_enrich_harness_run_attaches_diff_summary() -> None:
    report = _make_report()
    harness = _make_harness(report=report)

    result = enrich_harness_run(harness, "test intent")

    assert result.is_ok()
    enriched = result.unwrap()
    assert enriched.artifacts["change_summary"] != ""
    assert enriched.artifacts["file_diff"] != ""
    assert enriched.artifacts["extra"] == "value"
    # Metadata from the original Rooted result must be preserved.
    assert result.assumption == "plan executed"
    assert result.confidence == 0.95
    assert "harness_report_enricher.attach_diff_summary" in result.provenance


def test_enrich_harness_run_propagates_error() -> None:
    harness = _make_harness(error="plan invalid")

    result = enrich_harness_run(harness, "bad intent")

    assert not result.is_ok()
    assert result.error == "plan invalid"


def test_enrich_harness_run_handles_exception() -> None:
    harness = MagicMock(spec=Harness)
    harness.run.side_effect = RuntimeError("harness crashed")

    result = enrich_harness_run(harness, "intent")

    assert not result.is_ok()
    assert "harness crashed" in (result.error or "")


def test_enrich_harness_run_no_steps() -> None:
    report = ExecutionReport(
        intent="empty",
        step_results=[],
        assumptions=[],
        provenance={},
        artifacts={},
    )
    harness = _make_harness(report=report)

    result = enrich_harness_run(harness, "empty intent")

    assert result.is_ok()
    assert result.unwrap().artifacts["change_summary"] != ""
    assert result.unwrap().artifacts["file_diff"] != ""


# RACT 0.1.1 - Trust and tooling
