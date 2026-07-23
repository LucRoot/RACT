# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Assumption register and decision log.

Builds a human-readable Markdown register from a plan (assumptions) and a
list of execution results (outcomes). Useful for compliance, audits, and
post-run reasoning traces.
"""

from typing import Any


def confidence_stats(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Return aggregate statistics over a list of result dicts.

    Each result dict should contain at least a numeric ``confidence`` key
    and optionally a boolean ``success`` key.
    """
    if not results:
        return {"mean_confidence": 0.0, "success_rate": 0.0, "count": 0}
    count = len(results)
    mean_confidence = sum(float(r.get("confidence", 0.0)) for r in results) / count
    success_rate = sum(1 for r in results if r.get("success")) / count
    return {
        "mean_confidence": mean_confidence,
        "success_rate": success_rate,
        "count": count,
    }


def build_register(plan: dict[str, dict[str, Any]], results: list[dict[str, Any]]) -> str:
    """Build a Markdown assumption register from a plan and its results.

    ``plan`` maps step identifiers to dicts describing the assumption,
    confidence, and provenance for that step. ``results`` is a list of
    execution outcome dicts used to compute aggregate statistics.
    """
    stats = confidence_stats(results)
    lines: list[str] = ["# Assumption Register\n"]
    for step_id, step in plan.items():
        lines.append(f"## Decision: {step_id}\n")
        lines.append(f"- Stated Assumption: {step.get('assumption', '')}\n")
        lines.append(f"- Confidence: {step.get('confidence', '')}\n")
        lines.append(f"- Provenance: {step.get('provenance', 'unknown')}\n")
    lines.append("## Outcome Summary\n")
    lines.append(f"- Total results: {stats['count']}\n")
    lines.append(f"- Mean confidence: {stats['mean_confidence']:.2f}\n")
    lines.append(f"- Success rate: {stats['success_rate']:.2f}\n")
    return "".join(lines)


# RACT 0.1.2 - Trust and tooling
