# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

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


class ProgressOracle(ABC):
    """Base class for oracles that decide whether RACT should move forward."""

    @abstractmethod
    def evaluate(self, context: dict[str, Any]) -> Rooted[ProgressVerdict]:
        """Return a verdict for the current loop state."""
        ...
