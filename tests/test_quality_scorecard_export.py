"""Tests for quality scorecard JSON export."""

from __future__ import annotations


import json

from ract.quality_scorecard import export_scorecard


def test_export_scorecard_round_trip(tmp_path):
    scorecard = {
        "total": 87.5,
        "threshold": 85.0,
        "passed": True,
        "signals": {"tests_pass": 20.0},
    }
    path = tmp_path / "scorecard.json"
    export_scorecard(scorecard, str(path))
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == scorecard


# RACT 0.1.1 - Trust and tooling
