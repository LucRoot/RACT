# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for consolidation HTML report renderer."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from ract.consolidate import ConsolidationResult, MergeProposal, render_html_report


def test_render_html_report_includes_proposal_and_consolidation():
    plan = ConsolidationResult(
        proposals=[
            MergeProposal(
                target="src/ract/core.py",
                sources=("src/ract/old_core.py",),
                diff="-old\n+new",
                reason="near-duplicate",
            )
        ],
        metrics={"candidates": 2, "predicted_line_reduction": 42},
    )
    html = render_html_report(plan)
    assert "Consolidation Report" in html
    assert "src/ract/core.py" in html
    assert "consolidation" in html.lower()
    assert "42" in html
