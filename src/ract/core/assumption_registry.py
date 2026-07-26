"""AssumptionRegistry with violation propagation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeVar

from ract.core.assumption import (
    Assumed,
    Assumption,
    AssumptionId,
    AssumptionState,
    Evidence,
    Violation,
)


@dataclass
class AssumptionRegistry:
    """Single source of truth for assumption lifecycle."""

    _assumptions: dict[AssumptionId, Assumption] = field(default_factory=dict)

    def propose(
        self, text: str, depends_on: tuple[AssumptionId, ...] = ()
    ) -> Assumption:
        """Propose a new assumption and return it."""
        assumption = Assumption.propose(text, depends_on)
        self._assumptions[assumption.id] = assumption
        _emit_assumption_event(
            "assumption.proposed",
            {
                "assumption_id": assumption.id.hex(),
                "digest": assumption.digest.hex(),
                "text": text,
            },
        )
        return assumption

    def accept(self, assumption_id: AssumptionId) -> Assumption:
        """Move a PROPOSED assumption to ACTIVE."""
        assumption = self._get(assumption_id)
        if assumption.state != AssumptionState.PROPOSED:
            raise ValueError(f"assumption {assumption_id.hex()} is not proposed")
        updated = Assumption(
            id=assumption.id,
            text=assumption.text,
            digest=assumption.digest,
            state=AssumptionState.ACTIVE,
            depends_on=assumption.depends_on,
        )
        self._assumptions[assumption_id] = updated
        return updated

    def discharge(self, assumption_id: AssumptionId, evidence: Evidence) -> Assumption:
        """Discharge an ACTIVE assumption with evidence."""
        assumption = self._get(assumption_id)
        if assumption.state not in (AssumptionState.ACTIVE, AssumptionState.PROPOSED):
            raise ValueError(f"assumption {assumption_id.hex()} cannot be discharged")
        updated = Assumption(
            id=assumption.id,
            text=assumption.text,
            digest=assumption.digest,
            state=AssumptionState.DISCHARGED,
            depends_on=assumption.depends_on,
            discharged_by=evidence,
        )
        self._assumptions[assumption_id] = updated
        _emit_assumption_event(
            "assumption.discharged",
            {
                "assumption_id": assumption_id.hex(),
                "digest": assumption.digest.hex(),
            },
        )
        return updated

    def violate(
        self, assumption_id: AssumptionId, violation: Violation
    ) -> list[AssumptionId]:
        """Mark an assumption VIOLATED and propagate to all dependents.

        Returns the list of assumption IDs that were marked violated.
        """
        assumption = self._get(assumption_id)
        if assumption.state == AssumptionState.VIOLATED:
            return []
        updated = Assumption(
            id=assumption.id,
            text=assumption.text,
            digest=assumption.digest,
            state=AssumptionState.VIOLATED,
            depends_on=assumption.depends_on,
            discharged_by=assumption.discharged_by,
            violated_by=violation,
        )
        self._assumptions[assumption_id] = updated
        violated: list[AssumptionId] = [assumption_id]

        # Propagate through the dependency graph.
        frontier = {assumption_id}
        while frontier:
            current = frontier.pop()
            for candidate in self._assumptions.values():
                if candidate.state == AssumptionState.VIOLATED:
                    continue
                if current in candidate.depends_on:
                    frontier.add(candidate.id)
                    self._assumptions[candidate.id] = Assumption(
                        id=candidate.id,
                        text=candidate.text,
                        digest=candidate.digest,
                        state=AssumptionState.VIOLATED,
                        depends_on=candidate.depends_on,
                        discharged_by=candidate.discharged_by,
                        violated_by=violation,
                    )
                    violated.append(candidate.id)
        for vid in violated:
            _emit_assumption_event(
                "assumption.violated",
                {
                    "assumption_id": vid.hex(),
                    "root_id": assumption_id.hex(),
                },
            )
        return violated

    def get(self, assumption_id: AssumptionId) -> Assumption | None:
        """Return the assumption or None."""
        return self._assumptions.get(assumption_id)

    def violated(self) -> list[Assumption]:
        """Return every assumption currently in the VIOLATED state."""
        return [
            assumption
            for assumption in self._assumptions.values()
            if assumption.state == AssumptionState.VIOLATED
        ]

    def invalid_assumed(self, assumed_items: list[Assumed]) -> list[Assumed]:
        """Return every Assumed whose assumption is not active/discharged."""
        return [item for item in assumed_items if not item.is_valid(self)]

    def _get(self, assumption_id: AssumptionId) -> Assumption:
        assumption = self._assumptions.get(assumption_id)
        if assumption is None:
            raise KeyError(f"assumption {assumption_id.hex()} not found")
        return assumption


T = TypeVar("T")


def _emit_assumption_event(kind: str, payload: dict) -> None:
    """Emit an assumption lifecycle event to the event log.

    module_05 (SUBSTRATE §6.3). Local import so the assumption module
    stays trace-independent at import time.
    """
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(kind, payload)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        pass


def bind_assumption(value: T, registry: AssumptionRegistry, text: str) -> Assumed[T]:
    """Lift ``value`` into an Assumed[T] backed by a new registry assumption."""
    assumption = registry.propose(text)
    registry.accept(assumption.id)
    return Assumed(value=value, assumption_id=assumption.id)


# RACT 0.2.0
