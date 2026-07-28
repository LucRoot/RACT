from __future__ import annotations


"""Statistically defensible provider scorecard for RACT.

Aggregates a corpus of run receipts into per-provider statistics that can be
shown on a public leaderboard without inviting ``n=3`` critiques.
"""

import statistics
from typing import Iterable


def compute_scorecard(receipts: Iterable[dict], min_samples: int = 10) -> dict:
    """Return per-provider statistics for providers with enough samples."""
    groups: dict[str, list[dict]] = {}
    for receipt in receipts:
        provider = receipt.get("provider")
        if not provider:
            continue
        groups.setdefault(provider, []).append(receipt)

    result: dict[str, dict] = {}
    for provider, group in groups.items():
        if len(group) < min_samples:
            continue
        n = len(group)
        result[provider] = {
            "success_rate": sum(r.get("success", 0) for r in group) / n,
            "median_latency": statistics.median(r.get("latency", 0.0) for r in group),
            "median_quality": statistics.median(r.get("quality", 0.0) for r in group),
            "total_cost": sum(r.get("cost", 0.0) for r in group),
            "sample_count": n,
        }
    return result


# RACT 0.1.2 - Trust and tooling
