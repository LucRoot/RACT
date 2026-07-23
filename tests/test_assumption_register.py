# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for rootact.assumption_register."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.assumption_register import build_register, confidence_stats


def test_confidence_stats_empty():
    assert confidence_stats([]) == {
        "mean_confidence": 0.0,
        "success_rate": 0.0,
        "count": 0,
    }


def test_confidence_stats_basic():
    results = [
        {"success": True, "confidence": 0.8},
        {"success": False, "confidence": 0.9},
    ]
    stats = confidence_stats(results)
    assert stats["count"] == 2
    assert abs(stats["mean_confidence"] - 0.85) < 1e-9
    assert stats["success_rate"] == 0.5


def test_build_register_sections():
    plan = {
        "step_a": {
            "assumption": "x is stable",
            "confidence": 0.8,
            "provenance": "manual",
        }
    }
    results = [{"success": True, "confidence": 0.9, "provenance": "test"}]
    doc = build_register(plan, results)
    assert "# Assumption Register" in doc
    assert "## Decision: step_a" in doc
    assert "Stated Assumption: x is stable" in doc
    assert "Confidence: 0.8" in doc
    assert "Provenance: manual" in doc
    assert "## Outcome Summary" in doc
    assert "Total results: 1" in doc


# RACT 0.1.2 - Trust and tooling
