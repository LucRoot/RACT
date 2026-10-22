"""The VERIFIER's result: what the harness ran, and whether it backs the turn.

LR:: ADR-0049 D4: a step is done when a check recorded after its last change
passes. The VERIFIER is harness code, not a model role, so this record holds
only what the harness measured: the commands it ran, their exit codes and
how many changes each run had seen. A model's text never adds a run. A turn
whose answer claims success ("tests pass") with no passing run after the
last change is `unverified`, and the summary says so.

The record's ``to_event()`` is the ``verification`` object of
``turn.finished`` (docs/EVENTS_SESSION.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal["verified", "failed", "stale", "no-tests", "not-run"]


@dataclass(frozen=True)
class CheckRun:
    """One check command the harness ran."""

    command: tuple[str, ...]
    exit_code: int
    duration_ms: int
    # How many changes the turn had made when this run started.
    changes_seen: int

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    def to_event(self) -> dict[str, Any]:
        return {
            "command": " ".join(self.command),
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class VerificationResult:
    """The verification facts for one turn."""

    status: Status
    runs: tuple[CheckRun, ...] = ()
    claims: tuple[str, ...] = ()

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    def label(self) -> Literal["verified", "unverified"]:
        """`verified` only when a passing run backs the last change.

        A claim in the answer text never changes this: a model saying the
        tests pass is not a run.
        """
        return "verified" if self.verified else "unverified"

    def to_event(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "runs": [run.to_event() for run in self.runs],
            "claims": list(self.claims),
        }


@dataclass
class VerificationRecord:
    """Collects the turn's changes and check runs, in order.

    Only harness code calls :meth:`note_change` and :meth:`record`.
    """

    tests_found: bool = True
    _changes: int = 0
    _runs: list[CheckRun] = field(default_factory=list)

    def note_change(self) -> None:
        """A file was written or replaced."""
        self._changes += 1

    def record(
        self, command: list[str] | tuple[str, ...], exit_code: int, duration_ms: int
    ) -> None:
        """A check command finished with ``exit_code``."""
        self._runs.append(
            CheckRun(
                command=tuple(str(part) for part in command),
                exit_code=int(exit_code),
                duration_ms=int(duration_ms),
                changes_seen=self._changes,
            )
        )

    def result(self, claims: list[str] | tuple[str, ...] = ()) -> VerificationResult:
        """The turn's VerificationResult.

        ``claims`` are the success claims found in the turn's answer text
        (turn_summary.unverified_claims). A verified turn backs them, so
        they are dropped; otherwise they stay and the turn is unverified.
        """
        runs = tuple(self._runs)
        if not runs:
            status: Status = "not-run" if self.tests_found else "no-tests"
        else:
            current = [run for run in runs if run.changes_seen == self._changes]
            if not current:
                status = "stale"
            elif all(run.passed for run in current):
                status = "verified"
            else:
                status = "failed"
        kept = () if status == "verified" else tuple(dict.fromkeys(claims))
        return VerificationResult(status=status, runs=runs, claims=kept)


NOT_RUN = VerificationResult(status="not-run")

__all__ = ["CheckRun", "NOT_RUN", "Status", "VerificationRecord", "VerificationResult"]
