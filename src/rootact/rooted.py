# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Rooted types — the Root signature quirk.

Most code hides its assumptions. Rooted makes them explicit. Every Rooted value
carries the load-bearing assumption that justifies it, a confidence score, and a
provenance chain. If confidence drops below the floor, the chain short-circuits.

It is an odd way to thread state, but it keeps the system honest about what it
actually knows.
"""

from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

T = TypeVar("T")
U = TypeVar("U")

# LR:: The default confidence floor below which a Rooted chain refuses to proceed.
DEFAULT_CONFIDENCE_FLOOR = 0.7


@dataclass(frozen=True)
class Rooted(Generic[T]):
    """A value anchored to the assumption that justifies it."""

    value: T | None = None
    assumption: str = ""
    confidence: float = 1.0
    provenance: list[str] = field(default_factory=list)
    error: str | None = None
    hint: str | None = None
    provider: str | None = None

    def is_ok(self) -> bool:
        """Return True if the value is usable and confidence is above floor."""
        return (
            self.error is None
            and self.confidence >= DEFAULT_CONFIDENCE_FLOOR
            and self.value is not None
        )

    def with_step(self, name: str) -> "Rooted[T]":
        """Return a new Rooted with an added provenance step."""
        return Rooted(
            value=self.value,
            assumption=self.assumption,
            confidence=self.confidence,
            provenance=[*self.provenance, name],
            error=self.error,
            hint=self.hint,
            provider=self.provider,
        )

    def unwrap(self) -> T:
        """Return the value or raise if the chain has failed."""
        if self.value is None:
            raise ValueError(f"Rooted value is missing: {self.error}")
        return self.value


def root_bind(
    rooted: Rooted[T],
    fn: Callable[[T], Rooted[U]],
    *,
    step: str = "",
) -> Rooted[U]:
    """Thread a Rooted value through a function that returns another Rooted.

    If the input is not ok, the failure propagates without calling fn.
    """
    if step:
        rooted = rooted.with_step(step)
    if not rooted.is_ok():
        return Rooted(
            value=None,
            assumption=rooted.assumption,
            confidence=rooted.confidence,
            provenance=rooted.provenance,
            error=rooted.error or f"confidence {rooted.confidence} below floor",
        )
    assert rooted.value is not None
    result = fn(rooted.value)
    return Rooted(
        value=result.value,
        assumption=result.assumption,
        confidence=result.confidence,
        provenance=[*rooted.provenance, *result.provenance],
        error=result.error,
        hint=result.hint,
        provider=result.provider,
    )


def root_map(rooted: Rooted[T], fn: Callable[[T], U], *, step: str = "") -> Rooted[U]:
    """Transform the value inside a Rooted without changing its metadata."""
    if step:
        rooted = rooted.with_step(step)
    if not rooted.is_ok():
        return Rooted(
            value=None,
            assumption=rooted.assumption,
            confidence=rooted.confidence,
            provenance=rooted.provenance,
            error=rooted.error,
            hint=rooted.hint,
            provider=rooted.provider,
        )
    assert rooted.value is not None
    return Rooted(
        value=fn(rooted.value),
        assumption=rooted.assumption,
        confidence=rooted.confidence,
        provenance=rooted.provenance,
        hint=rooted.hint,
        provider=rooted.provider,
    )


def root_assert(condition: bool, assumption: str, score: float = 1.0) -> Rooted[bool]:
    """Lift a boolean assertion into a Rooted result."""
    if condition:
        return Rooted(value=True, assumption=assumption, confidence=score)
    return Rooted(
        value=False,
        assumption=assumption,
        confidence=score,
        error=f"Assumption failed: {assumption}",
    )


# RACT 0.1.1 - Trust and Tooling
