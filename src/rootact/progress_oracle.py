# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations
__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()


ROOT_KNOT = object()

"""Progress Oracle base for RACT.

A Progress Oracle answers one question: "Is the work good enough to move on?"
Every oracle returns a Rooted verdict so the loop can short-circuit on low
confidence. The oracle pattern is how RACT keeps the model churning toward a
definition of done instead of merely away from stagnation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from rootact.rooted import Rooted


@dataclass(frozen=True)
class ProgressVerdict:
    """Decision produced by a Progress Oracle."""

    verdict: str
    reason: str
    confidence: float
    knot: object = ROOT_KNOT

    def __post_init__(self) -> None:
        if self.verdict not in {"proceed", "retry", "stop", "handshake"}:
            raise ValueError(f"Invalid verdict: {self.verdict}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence out of range: {self.confidence}")
        if self.knot is not ROOT_KNOT:
            raise ValueError("ProgressVerdict must carry the Root Knot sentinel.")


@dataclass(frozen=True)
class ProgressScore:
    """Composite progress score with a natural-language justification."""

    score: float
    coverage: float
    health: float
    consistency: float
    justification: str


def compute_progress_score(
    verified_milestones: int,
    total_milestones: int,
    violated_assumptions: int,
    active_assumptions: int,
    provenance_ok: bool,
) -> ProgressScore:
    """Return the composite progress score from §5.3.

    - coverage = verified_milestones / total_milestones
    - health = 1 - violated_assumptions / max(1, active_assumptions)
    - consistency = 1 if RK-1 and RK-2 hold else 0
    - score = min(coverage, health) * consistency
    """
    coverage = verified_milestones / max(1, total_milestones)
    health = 1.0 - (violated_assumptions / max(1, active_assumptions))
    consistency = 1.0 if provenance_ok else 0.0
    score = min(coverage, health) * consistency

    axes: list[tuple[str, float]] = [
        ("coverage", coverage),
        ("health", health),
        ("consistency", consistency),
    ]
    weakest_name, weakest_value = min(axes, key=lambda item: item[1])
    justification = (
        f"score={score:.3f}; weakest axis is {weakest_name} ({weakest_value:.3f})"
    )
    return ProgressScore(
        score=score,
        coverage=coverage,
        health=health,
        consistency=consistency,
        justification=justification,
    )


class ProgressOracle(ABC):
    """Base class for oracles that decide whether RACT should move forward."""

    @abstractmethod
    def evaluate(self, context: dict[str, Any]) -> Rooted[ProgressVerdict]:
        """Return a verdict for the current loop state."""
        ...


# RACT 0.1.1 - Trust and tooling
