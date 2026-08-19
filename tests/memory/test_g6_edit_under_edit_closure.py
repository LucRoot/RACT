"""module_09: G6 (under-edit closure) on the ``edit`` function's output.

Contract: ``enforce_g6_edit`` refuses when the :class:`CandidateDiff`
touches a file that isn't named in the :class:`ChangePlan`'s
``load_manifest``. A conforming diff passes silently.
"""

from __future__ import annotations

import pytest

from ract.antilazy import LazinessViolatedError, enforce_g6_edit
from ract.memory.functions.contracts import (
    CandidateDiff,
    ChangePlan,
    HunkSummary,
    Invariant,
    InvariantKind,
    RiskAssessment,
    RiskLevel,
    SymbolRef,
    TargetSymbol,
    VerificationCriterion,
)


def _plan(manifest_paths: tuple[str, ...]) -> ChangePlan:
    return ChangePlan(
        target_symbols=(
            TargetSymbol(symbol=SymbolRef(name="f", symbol_id=1), action="modify"),
        ),
        load_manifest=tuple(
            SymbolRef(name=f"s_{i}", file_path=p, symbol_id=i)
            for i, p in enumerate(manifest_paths, start=1)
        ),
        invariants=(
            Invariant(kind=InvariantKind.TEST_NAME, expression="tests/test_ok.py"),
        ),
        verification_criteria=(
            VerificationCriterion(predicate_id="p1", kind="test_passes"),
        ),
        risk_assessment=RiskAssessment(level=RiskLevel.LOW, rationale="tiny change"),
    )


def _diff(touched: tuple[str, ...]) -> CandidateDiff:
    return CandidateDiff(
        unified_diff="diff",
        hunks=tuple(
            HunkSummary(file_path=p, start_line=1, end_line=2, summary="x")
            for p in touched
        ),
        assembled_input_tokens=10,
        output_tokens=5,
    )


def test_diff_inside_manifest_passes() -> None:
    """A diff whose files are all in load_manifest passes silently."""
    plan = _plan(("src/a.py", "src/b.py"))
    diff = _diff(("src/a.py",))
    enforce_g6_edit(diff, plan)  # no raise


def test_diff_outside_manifest_raises() -> None:
    """A diff touching a file outside load_manifest raises."""
    plan = _plan(("src/a.py",))
    diff = _diff(("src/a.py", "src/rogue.py"))
    with pytest.raises(LazinessViolatedError) as exc:
        enforce_g6_edit(diff, plan)
    assert exc.value.kind == "under_edit_closure_gap"
    assert "src/rogue.py" in str(exc.value)


def test_diff_none_raises_diff_without_plan() -> None:
    """A None diff at the edit-path gate refuses loudly.

    The edit-path gate requires a CandidateDiff — legacy callers
    without one reach the older enforce_g6(transaction, graph,
    edited_symbols) surface instead.
    """
    plan = _plan(("src/a.py",))
    with pytest.raises(LazinessViolatedError) as exc:
        enforce_g6_edit(None, plan)
    assert exc.value.kind == "diff_without_plan"


def test_empty_manifest_and_empty_diff_passes() -> None:
    """A no-op diff against an empty manifest passes."""
    plan = _plan(())
    diff = _diff(())
    enforce_g6_edit(diff, plan)


def test_backslash_vs_forward_slash_normalized() -> None:
    """Second Pass Q3 fold: mixed separators do not miss a real match.

    A manifest entry written with Windows-style backslashes matches a
    diff hunk written with git's POSIX slashes and vice-versa.
    """
    # Manifest uses backslashes (Windows LSP), diff uses forward slashes.
    plan = _plan(("src\\a.py",))
    diff = _diff(("src/a.py",))
    enforce_g6_edit(diff, plan)  # normalized → same file → passes


def test_leading_dot_slash_normalized() -> None:
    """Second Pass Q3 fold: a leading './' does not trip the gate."""
    plan = _plan(("./src/a.py",))
    diff = _diff(("src/a.py",))
    enforce_g6_edit(diff, plan)


# RACT 0.5.0
