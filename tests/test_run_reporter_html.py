# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for run report HTML rendering."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.run_reporter import render_html_report


def test_render_html_report_includes_key_sections():
    report = {
        "final_decision": "completed",
        "summary": "all green",
        "metrics": {"total_tokens": 1000},
        "handshake_milestones": ["m1"],
        "iterations": [
            {"index": 0, "decision": "edit", "test_returncode": 0, "quality_score": 0.9}
        ],
    }
    html = render_html_report(report)
    assert "<h1>RACT Run Report</h1>" in html
    assert "completed" in html
    assert "<h2>Metrics</h2>" in html
    assert "<h2>Operator Handshakes</h2>" in html
    assert "<h2>Iterations</h2>" in html
    assert "#0" in html


# RACT 0.1.1 - Trust and tooling
