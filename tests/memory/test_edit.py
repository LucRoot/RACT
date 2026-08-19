"""Tests for :func:`ract.memory.functions.edit.edit`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.memory.functions import (
    CandidateDiff,
    ChangePlan,
    IndexBundle,
    Invariant,
    InvariantKind,
    InvalidSyntaxError,
    RiskAssessment,
    RiskLevel,
    SymbolRef,
    TargetSymbol,
    VerificationCriterion,
    edit,
)
from ract.memory.functions.edit import _validate_diff
from ract.memory.functions.testing import MockProvider


def _change_plan() -> ChangePlan:
    return ChangePlan(
        target_symbols=(
            TargetSymbol(
                symbol=SymbolRef(name="greet", file_path="greet.py"),
                action="rename",
                notes="greet -> say_hello",
            ),
        ),
        load_manifest=(SymbolRef(name="greet", file_path="greet.py"),),
        invariants=(Invariant(kind=InvariantKind.TEST_NAME, expression="test_greet"),),
        verification_criteria=(
            VerificationCriterion(
                predicate_id="P1", kind="test_passes", payload=(("test", "t"),)
            ),
        ),
        risk_assessment=RiskAssessment(level=RiskLevel.LOW, rationale="tiny"),
        iteration_bound=1,
    )


_VALID_DIFF_RESPONSE = json.dumps(
    {
        "unified_diff": (
            "--- a/greet.py\n"
            "+++ b/greet.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def greet():\n"
            "+def say_hello():\n"
            "     return 'hi'\n"
        ),
        "hunks": [
            {
                "file_path": "greet.py",
                "start_line": 1,
                "end_line": 2,
                "summary": "rename greet",
            }
        ],
    }
)


def test_edit_returns_candidate_diff_on_valid_response(tmp_path: Path):
    provider = MockProvider(responses_by_function={"edit": _VALID_DIFF_RESPONSE})
    result = edit(_change_plan(), IndexBundle(), provider)
    assert isinstance(result, CandidateDiff)
    assert "def say_hello" in result.unified_diff
    assert result.hunks[0].file_path == "greet.py"
    assert result.output_tokens > 0


def test_edit_retries_on_invalid_diff_syntax(tmp_path: Path):
    invalid_response = json.dumps(
        {
            "unified_diff": "TODO: implement rename",
            "hunks": [],
        }
    )
    # Two failures, one success on the third try (allowed under MAX_PARSE_RETRIES=2).
    provider = MockProvider()
    provider.responses_by_function = {"edit": invalid_response}
    with pytest.raises(InvalidSyntaxError):
        edit(_change_plan(), IndexBundle(), provider)


def test_edit_retries_then_succeeds(tmp_path: Path):
    """Provider returns a lazy diff twice, then a valid diff."""

    class RetryProvider:
        def __init__(self) -> None:
            self.responses = [
                json.dumps({"unified_diff": "TODO thing", "hunks": []}),
                json.dumps({"unified_diff": "TODO other", "hunks": []}),
                _VALID_DIFF_RESPONSE,
            ]
            self.calls = 0

        def send(self, prompt: str, declaration) -> str:
            self.calls += 1
            return self.responses[min(self.calls - 1, len(self.responses) - 1)]

    provider = RetryProvider()
    result = edit(_change_plan(), IndexBundle(), provider)
    assert "def say_hello" in result.unified_diff
    assert provider.calls == 3
    assert any("attempt 2" in note for note in result.validator_notes)


def test_validate_diff_rejects_forbidden_tokens():
    diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+TODO implement\n"
    report = _validate_diff(diff)
    assert not report.valid
    assert any("TODO" in reason for reason in report.reasons)


def test_validate_diff_rejects_ellipsis_bodies():
    diff = (
        "--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n-def f(): return 1\n+def f():\n+    ...\n"
    )
    report = _validate_diff(diff)
    assert not report.valid


def test_validate_diff_rejects_lazy_prose():
    diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+leave X unchanged\n"
    report = _validate_diff(diff)
    assert not report.valid


def test_validate_diff_accepts_valid_hunk():
    diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old value\n+new value\n"
    report = _validate_diff(diff)
    assert report.valid
