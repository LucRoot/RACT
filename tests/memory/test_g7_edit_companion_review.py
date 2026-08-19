"""module_09: G7 (companion review) on the ``edit`` function's output.

Contract: ``enforce_g7_edit(diff, companion)`` calls
``companion.review(diff) -> (approved: bool, reason: str)``. A False
verdict raises :class:`LazinessViolatedError` with
``kind="companion_flagged"``. A True verdict passes silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from ract.antilazy import LazinessViolatedError, enforce_g7_edit
from ract.memory.functions.contracts import CandidateDiff, HunkSummary


def _diff() -> CandidateDiff:
    return CandidateDiff(
        unified_diff="diff --git a/x b/x\n@@\n+ok\n",
        hunks=(HunkSummary(file_path="x", start_line=1, end_line=1, summary="x"),),
        assembled_input_tokens=100,
        output_tokens=10,
    )


@dataclass
class _CompanionSpy:
    approved: bool
    reason: str = ""
    calls: list[CandidateDiff] = field(default_factory=list)

    def review(self, diff: CandidateDiff) -> tuple[bool, str]:
        self.calls.append(diff)
        return self.approved, self.reason


def test_positive_verdict_passes() -> None:
    """approved=True → enforce_g7_edit returns without raising."""
    spy = _CompanionSpy(approved=True, reason="looks good")
    enforce_g7_edit(_diff(), spy)
    assert len(spy.calls) == 1


def test_negative_verdict_raises() -> None:
    """approved=False → enforce_g7_edit raises with kind=companion_flagged."""
    spy = _CompanionSpy(approved=False, reason="undefined behavior at line 42")
    with pytest.raises(LazinessViolatedError) as exc:
        enforce_g7_edit(_diff(), spy)
    assert exc.value.kind == "companion_flagged"
    assert "undefined behavior at line 42" in str(exc.value)


# RACT 0.5.0
