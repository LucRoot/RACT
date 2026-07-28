"""Tests for earned-coverage mutation gate integration."""

from __future__ import annotations


from ract.coverage_delta import CoverageDelta, CoverageSnapshot
from ract.mutation_merge_gate import MergePolicy, evaluate_coverage_policy


def _snapshot(percent: float) -> CoverageSnapshot:
    return CoverageSnapshot(
        percent_covered=percent,
        covered_lines=int(percent),
        missing_lines=100 - int(percent),
        total_lines=100,
    )


def test_evaluate_coverage_policy_passes_on_earn():
    delta = CoverageDelta(
        before=_snapshot(90.0),
        after=_snapshot(92.0),
        percent_delta=2.0,
        verdict="earn",
        detail="improved",
    )
    policies = [
        MergePolicy("p1", "require earn", ".*", "coverage_delta >= 0", 0.0, "block")
    ]
    assert evaluate_coverage_policy(policies, delta) is True


def test_evaluate_coverage_policy_fails_on_regress():
    delta = CoverageDelta(
        before=_snapshot(92.0),
        after=_snapshot(90.0),
        percent_delta=-2.0,
        verdict="regress",
        detail="worsened",
    )
    policies = [
        MergePolicy("p1", "require earn", ".*", "coverage_delta >= 0", 0.0, "block")
    ]
    assert evaluate_coverage_policy(policies, delta) is False


def test_evaluate_coverage_policy_fails_on_floor_breach():
    delta = CoverageDelta(
        before=_snapshot(90.0),
        after=_snapshot(92.0),
        percent_delta=2.0,
        verdict="earn",
        detail="improved but floor breached",
        floor_breached=True,
        per_file_breaches=["src/ract/core.py"],
    )
    policies = [
        MergePolicy("p1", "require earn", ".*", "coverage_delta >= 0", 0.0, "block")
    ]
    assert evaluate_coverage_policy(policies, delta) is False
