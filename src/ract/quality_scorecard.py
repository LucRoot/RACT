from __future__ import annotations


_SENTINEL = object()

"""Quality scoring for RACT.

The legacy plan-quality score rewards confidence and step count. The anti-rot
verifier rubric (v0.3) turns build/test/lint outcomes, diff minimality, secret
presence, entropy change, error-mask patterns, duplication similarity, and
codebase gravity into a single score with a completion threshold.
"""

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class Verdict:
    """Inputs for the anti-rot verifier rubric."""

    build_passes: bool = False
    tests_pass: bool = False
    lint_clean: bool = False
    imports_resolve: bool = False
    diff_minimal: bool = False
    no_secrets: bool = True
    net_entropy_change: float = 0.0
    error_mask_count: int = 0
    duplication_similarity: float = 0.0
    gravity_adherence: float = 1.0
    mutation_score: float = 0.0


class QualityScorecard:
    """Deterministic scorecard for plan quality and anti-rot verifier scoring."""

    # Anti-rot verifier rubric v0.4 weights.
    RUBRIC_WEIGHTS: dict[str, float] = {
        "build_passes": 20.0,
        "tests_pass": 20.0,
        "lint_clean": 10.0,
        "imports_resolve": 10.0,
        "diff_minimal": 8.0,
        "no_secrets": 7.0,
        "net_entropy_change": 10.0,
        "error_mask_patterns": -30.0,
        "duplication_guard": -20.0,
        "codebase_gravity": 5.0,
        "mutation_score": 10.0,
    }
    DEFAULT_THRESHOLD: float = 85.0

    def __init__(self, threshold: float = DEFAULT_THRESHOLD) -> None:
        self._records: list[dict[str, Any]] = []
        self.threshold = threshold

    def compute_score(self, plan: Any | None) -> float:
        """Compute a deterministic quality score from a plan.

        The score rewards both confidence and step count:
            confidence * step_count / (1 + step_count)
        """
        if plan is None:
            return 0.0
        steps = getattr(plan, "steps", None)
        if not steps:
            return 0.0
        confidence = float(getattr(plan, "confidence", 0.0))
        step_count = len(steps)
        return round(confidence * step_count / (1 + step_count), 3)

    def score_verdict(self, verdict: Verdict) -> dict[str, Any]:
        """Score an anti-rot verifier verdict and return a detailed breakdown.

        LR:: The rubric makes rot vectors first-class quality signals. A task
        that duplicates existing code or masks errors cannot pass without an
        explicit override, and every override is logged.
        """
        weights = self.RUBRIC_WEIGHTS
        signals: dict[str, float] = {}

        signals["build_passes"] = (
            weights["build_passes"] if verdict.build_passes else 0.0
        )
        signals["tests_pass"] = weights["tests_pass"] if verdict.tests_pass else 0.0
        signals["lint_clean"] = weights["lint_clean"] if verdict.lint_clean else 0.0
        signals["imports_resolve"] = (
            weights["imports_resolve"] if verdict.imports_resolve else 0.0
        )
        signals["diff_minimal"] = (
            weights["diff_minimal"] if verdict.diff_minimal else 0.0
        )
        signals["no_secrets"] = weights["no_secrets"] if verdict.no_secrets else 0.0

        # Net entropy change: negative delta (deletion/simplification) earns a
        # bonus up to the 10-point weight; positive delta contributes nothing.
        # A normalized entropy delta of -1.0 maps to the full 10-point bonus.
        entropy_bonus = max(
            0.0,
            min(
                weights["net_entropy_change"],
                -verdict.net_entropy_change * weights["net_entropy_change"],
            ),
        )
        signals["net_entropy_change"] = round(entropy_bonus, 2)

        # Error-mask penalty: -8 per instance, capped at -30.
        mask_penalty = max(
            weights["error_mask_patterns"], -8.0 * verdict.error_mask_count
        )
        signals["error_mask_patterns"] = round(mask_penalty, 2)

        # Duplication penalty: similarity scaled to -20 max.
        dup_penalty = weights["duplication_guard"] * verdict.duplication_similarity
        signals["duplication_guard"] = round(dup_penalty, 2)

        # Gravity adherence: full weight when adherence is 1.0, scaled down.
        signals["codebase_gravity"] = round(
            weights["codebase_gravity"] * max(0.0, min(1.0, verdict.gravity_adherence)),
            2,
        )

        # Mutation score: 0-100 scale mapped to the rubric weight.
        signals["mutation_score"] = round(
            weights["mutation_score"]
            * max(0.0, min(1.0, verdict.mutation_score / 100.0)),
            2,
        )

        total = round(sum(signals.values()), 2)
        passed = total >= self.threshold

        return {
            "total": total,
            "threshold": self.threshold,
            "passed": passed,
            "signals": signals,
            "verdict": {
                "build_passes": verdict.build_passes,
                "tests_pass": verdict.tests_pass,
                "lint_clean": verdict.lint_clean,
                "imports_resolve": verdict.imports_resolve,
                "diff_minimal": verdict.diff_minimal,
                "no_secrets": verdict.no_secrets,
                "net_entropy_change": verdict.net_entropy_change,
                "error_mask_count": verdict.error_mask_count,
                "duplication_similarity": verdict.duplication_similarity,
                "gravity_adherence": verdict.gravity_adherence,
                "mutation_score": verdict.mutation_score,
            },
        }

    def passes_threshold(self, verdict: Verdict) -> bool:
        """Return True if the verdict meets or exceeds the completion threshold."""
        return self.score_verdict(verdict)["passed"]

    def record_score(self, plan: Any | None) -> None:
        """Record the computed legacy score for later retrieval."""
        self._records.append({"score": self.compute_score(plan)})

    def record_verdict(self, verdict: Verdict) -> None:
        """Record the scored anti-rot verdict for later retrieval."""
        self._records.append(self.score_verdict(verdict))

    def get_scores(self) -> list[dict[str, Any]]:
        """Return a copy of all recorded scores."""
        return list(self._records)

    def clear(self) -> None:
        """Reset the internal record store."""
        self._records.clear()

    def __len__(self) -> int:
        return len(self._records)

    def __bool__(self) -> bool:
        return bool(self._records)

    def write_to_file(self, path: str) -> None:
        """Write the current records as JSON to the given file path."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.get_scores(), f, indent=2)

    def read_from_file(self, path: str) -> None:
        """Load records from a JSON file, replacing current records."""
        with open(path, "r", encoding="utf-8") as f:
            self._records = json.load(f)


def export_scorecard(scorecard: dict[str, Any], path: str) -> None:
    """Write a scorecard dict to *path* as formatted JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scorecard, f, indent=2)


# RACT 0.1.1 - Trust and tooling
