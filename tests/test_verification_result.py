"""ADR-0049 D4: the VERIFIER result type, and the done rule it carries."""

from __future__ import annotations

from ract import turn_summary
from ract.verification import NOT_RUN, VerificationRecord

ROLE_OUTPUT = "I fixed add() in src/calc.py. All tests pass now."


def test_a_success_claim_without_a_verifier_record_leaves_the_turn_unverified() -> None:
    # The acceptance test from the roles workstream: a role output that
    # claims success, and no run recorded by the harness.
    record = VerificationRecord()
    record.note_change()

    result = record.result(turn_summary.unverified_claims(ROLE_OUTPUT))

    assert result.status == "not-run"
    assert result.label() == "unverified"
    assert result.claims  # the claim is reported, not believed
    assert result.to_event()["runs"] == []


def test_a_passing_run_after_the_last_change_verifies_and_backs_the_claim() -> None:
    record = VerificationRecord()
    record.note_change()
    record.record(["pytest", "-q"], 0, 1290)

    result = record.result(turn_summary.unverified_claims(ROLE_OUTPUT))

    assert result.status == "verified" and result.label() == "verified"
    assert result.claims == ()
    assert result.to_event() == {
        "status": "verified",
        "runs": [{"command": "pytest -q", "exit_code": 0, "duration_ms": 1290}],
        "claims": [],
    }


def test_a_change_after_the_passing_run_makes_it_stale() -> None:
    record = VerificationRecord()
    record.note_change()
    record.record(["pytest", "-q"], 0, 10)
    record.note_change()

    result = record.result(["tests pass"])

    assert result.status == "stale" and result.label() == "unverified"
    assert result.claims == ("tests pass",)


def test_a_failing_run_after_the_last_change_is_failed() -> None:
    record = VerificationRecord()
    record.note_change()
    record.record(["pytest", "-q"], 0, 10)
    record.record(["ruff", "check", "src"], 1, 5)

    result = record.result()

    assert result.status == "failed" and result.label() == "unverified"
    assert [run["exit_code"] for run in result.to_event()["runs"]] == [0, 1]


def test_no_runs_and_no_tests_found_is_no_tests() -> None:
    result = VerificationRecord(tests_found=False).result()

    assert result.status == "no-tests" and result.label() == "unverified"


def test_not_run_is_the_default_turn_object() -> None:
    assert NOT_RUN.to_event() == {"status": "not-run", "runs": [], "claims": []}


def test_claims_are_kept_once_each() -> None:
    result = VerificationRecord().result(["tests pass", "tests pass", "verified"])

    assert result.claims == ("tests pass", "verified")
