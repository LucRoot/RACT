"""Assumption lifecycle and Assumed[T] wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, Protocol, TypeVar

from rootact.core.types import AssumptionId, Digest, digest_bytes, make_assumption_id


class _AssumptionRegistry(Protocol):
    """Minimal interface needed by Assumed[T] without a circular import."""

    def get(self, assumption_id: AssumptionId) -> Assumption | None: ...
    def discharge(self, assumption_id: AssumptionId, evidence: Evidence) -> Assumption: ...


class AssumptionState(Enum):
    """Four-state lifecycle of an assumption."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    DISCHARGED = "discharged"
    VIOLATED = "violated"


@dataclass(frozen=True)
class Evidence:
    """Evidence that discharges an assumption."""

    text: str
    artifact_digest: Digest | None = None


@dataclass(frozen=True)
class Violation:
    """Evidence that contradicts an assumption."""

    text: str
    artifact_digest: Digest | None = None


@dataclass(frozen=True)
class Assumption:
    """A load-bearing statement with a lifecycle and dependency graph."""

    id: AssumptionId
    text: str
    digest: Digest
    state: AssumptionState = AssumptionState.PROPOSED
    depends_on: tuple[AssumptionId, ...] = field(default_factory=tuple)
    discharged_by: Evidence | None = None
    violated_by: Violation | None = None

    @classmethod
    def propose(
        cls,
        text: str,
        depends_on: tuple[AssumptionId, ...] = (),
    ) -> Assumption:
        """Create a new PROPOSED assumption."""
        assumption_id = make_assumption_id()
        canonical = f"{assumption_id.hex()}:{text}:{','.join(d.hex() for d in depends_on)}".encode()
        return cls(
            id=assumption_id,
            text=text,
            digest=digest_bytes(canonical),
            state=AssumptionState.PROPOSED,
            depends_on=depends_on,
        )


T = TypeVar("T")


@dataclass(frozen=True)
class Assumed(Generic[T]):
    """A value bound to the assumption that justifies it."""

    value: T
    assumption_id: AssumptionId

    def is_valid(self, registry: _AssumptionRegistry) -> bool:
        """Return True when the underlying assumption is active or discharged."""
        assumption = registry.get(self.assumption_id)
        if assumption is None:
            return False
        return assumption.state in (
            AssumptionState.ACTIVE,
            AssumptionState.DISCHARGED,
        )

    def discharge(self, registry: _AssumptionRegistry, evidence: Evidence) -> T:
        """Discharge the underlying assumption and return the wrapped value."""
        registry.discharge(self.assumption_id, evidence)
        return self.value


# RACT 0.2.0
