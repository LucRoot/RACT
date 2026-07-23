from __future__ import annotations


"""Calibrate complexity-router tier boundaries from historical receipts.

The calibrator consumes records that contain a pre-computed complexity score
and an observed cost proxy (cost, tokens, or latency).  It searches for score
boundaries that best separate cheap work from expensive work, then emits
recommended low / medium / high thresholds for `ComplexityRouter`.
"""

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ract.complexity_router import ComplexityRouter


@dataclass
class CalibrationRecord:
    """One historical observation used to calibrate tier boundaries."""

    complexity_score: float = 0.0
    tokens: float = 0.0
    latency_ms: float = 0.0
    cost: float = 0.0
    tier: str = ""
    task_id: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalibrationRecord":
        return cls(
            complexity_score=float(data.get("complexity_score") or 0.0),
            tokens=float(data.get("tokens") or 0.0),
            latency_ms=float(data.get("latency_ms") or 0.0),
            cost=float(data.get("cost") or 0.0),
            tier=str(data.get("tier") or ""),
            task_id=str(data.get("task_id") or ""),
        )


@dataclass
class TierSummary:
    """Aggregated statistics for a tier."""

    count: int = 0
    mean_cost: float = 0.0
    mean_tokens: float = 0.0
    mean_latency_ms: float = 0.0
    mean_score: float = 0.0
    min_score: float = 0.0
    max_score: float = 0.0


class ComplexityCalibrator:
    """Learn tighter tier boundaries from historical run records.

    Records are sorted by ``complexity_score``.  The calibrator tries every
    pair of split points that divides the sorted history into three non-empty
    groups and picks the split that minimises the total within-group variance
    of the normalised cost proxy.  The boundary scores between those groups
    become the recommended ``low`` and ``medium`` thresholds; the ``high``
    threshold is set to the maximum observed score so that anything more
    expensive lands in ``frontier``.

    With fewer than six records the calibrator falls back to simple
    percentile-based boundaries, and with fewer than three records it returns
    the default ``ComplexityRouter`` thresholds.
    """

    DEFAULT_THRESHOLDS = ComplexityRouter.DEFAULT_THRESHOLDS

    def __init__(self) -> None:
        self.records: List[CalibrationRecord] = []
        self._thresholds: Optional[Dict[str, float]] = None

    @staticmethod
    def _cost_proxy(record: CalibrationRecord) -> float:
        """Return a single cost value for a record, preferring explicit cost."""
        return record.cost or record.tokens or record.latency_ms or 0.0

    def fit(self, records: List[Dict[str, Any]]) -> "ComplexityCalibrator":
        """Fit thresholds to ``records`` and return ``self``."""
        self.records = sorted(
            (CalibrationRecord.from_dict(r) for r in records),
            key=lambda r: r.complexity_score,
        )
        if len(self.records) < 3:
            self._thresholds = None
            return self

        sorted_recs = self.records
        costs = [self._cost_proxy(r) for r in sorted_recs]
        max_cost = max(costs) or 1.0
        norm_costs = [c / max_cost for c in costs]
        scores = [r.complexity_score for r in sorted_recs]
        n = len(sorted_recs)

        if n < 6:
            self._thresholds = {
                "low": round(scores[n // 3], 4),
                "medium": round(scores[2 * n // 3], 4),
                "high": round(scores[-1], 4),
            }
            return self

        best_i: Optional[int] = None
        best_j: Optional[int] = None
        best_variance = math.inf

        for i in range(0, n - 2):
            for j in range(i + 1, n - 1):
                groups = [
                    norm_costs[: i + 1],
                    norm_costs[i + 1 : j + 1],
                    norm_costs[j + 1 :],
                ]
                if any(not g for g in groups):
                    continue
                total_variance = 0.0
                for g in groups:
                    mean = sum(g) / len(g)
                    total_variance += sum((x - mean) ** 2 for x in g)
                if total_variance < best_variance:
                    best_variance = total_variance
                    best_i = i
                    best_j = j

        if best_i is None or best_j is None:
            self._thresholds = dict(self.DEFAULT_THRESHOLDS)
            return self

        self._thresholds = {
            "low": round((scores[best_i] + scores[best_i + 1]) / 2, 4),
            "medium": round((scores[best_j] + scores[best_j + 1]) / 2, 4),
            "high": round(scores[-1], 4),
        }
        return self

    def recommend_thresholds(self) -> Dict[str, float]:
        """Return calibrated thresholds, or defaults if not enough data."""
        if self._thresholds is None:
            return dict(self.DEFAULT_THRESHOLDS)
        return dict(self._thresholds)

    def apply_to_router(self, router: ComplexityRouter) -> None:
        """Mutate ``router.thresholds`` with the calibrated values."""
        router.thresholds = self.recommend_thresholds()

    def _tier_for_score(self, score: float, thresholds: Dict[str, float]) -> str:
        if score <= thresholds.get("low", 0.30):
            return "low"
        if score <= thresholds.get("medium", 0.55):
            return "medium"
        if score <= thresholds.get("high", 0.80):
            return "high"
        return "frontier"

    def per_tier_summary(self) -> Dict[str, TierSummary]:
        """Summarise historical records grouped by their recommended tier."""
        thresholds = self.recommend_thresholds()
        groups: Dict[str, List[CalibrationRecord]] = {
            "low": [],
            "medium": [],
            "high": [],
            "frontier": [],
        }
        for rec in self.records:
            groups[self._tier_for_score(rec.complexity_score, thresholds)].append(rec)

        summary: Dict[str, TierSummary] = {}
        for tier, group in groups.items():
            if not group:
                summary[tier] = TierSummary()
                continue
            scores = [r.complexity_score for r in group]
            summary[tier] = TierSummary(
                count=len(group),
                mean_cost=round(sum(r.cost for r in group) / len(group), 6),
                mean_tokens=round(sum(r.tokens for r in group) / len(group), 6),
                mean_latency_ms=round(sum(r.latency_ms for r in group) / len(group), 6),
                mean_score=round(sum(scores) / len(scores), 4),
                min_score=round(min(scores), 4),
                max_score=round(max(scores), 4),
            )
        return summary

    def fit_summary(self) -> Dict[str, Any]:
        """Return thresholds plus per-tier summary in one dict."""
        return {
            "thresholds": self.recommend_thresholds(),
            "per_tier_summary": {
                tier: {
                    "count": s.count,
                    "mean_cost": s.mean_cost,
                    "mean_tokens": s.mean_tokens,
                    "mean_latency_ms": s.mean_latency_ms,
                    "mean_score": s.mean_score,
                    "min_score": s.min_score,
                    "max_score": s.max_score,
                }
                for tier, s in self.per_tier_summary().items()
            },
        }
