# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for run report JSON export."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json

from rootact.run_reporter import export_report


def test_export_report_roundtrips(tmp_path):
    report = {
        "final_decision": "done",
        "summary": "all green",
        "iterations": [{"index": 0, "decision": "done", "test_returncode": 0}],
    }
    out = tmp_path / "report.json"
    export_report(report, out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded == report
