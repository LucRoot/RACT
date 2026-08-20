"""T8 PROMPT_DRIFT termination cause -- unit tests (v0.5.1 module_04).

Locks the enum member into the closed vocabulary AND asserts that every
switch/dispatch surface handles the new value. Currently ``TerminationCause``
is enumerated only in ``ract.core.loop`` (the enum module) and referenced
by string-comparison in test suites -- there is no runtime match/switch
that must be extended. This file locks that invariant: any new switch
introduced by a later module must be extended here.
"""

from __future__ import annotations

import hashlib


from ract.core.loop import (
    Budget,
    LoopState,
    ProviderTimeoutRecord,
    TerminationCause,
    WorkspaceSnapshot,
    check_t8,
    evaluate_termination,
)
from ract.core.predicate import (
    AcceptancePredicate,
    AcceptanceSuite,
    ArtifactInvocation,
    new_intent_id,
    new_predicate_id,
)
from ract.handshake_registry import HandshakeRegistry
from ract.manager import Plan


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _suite_with_prompt(prompt_text: str) -> AcceptanceSuite:
    """Return a minimal always-failing suite bound to ``prompt_text``."""
    predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(
            path="__never_present__", must_have_rootknot=False
        ),
        required=True,
    )
    return AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(predicate,),
        compiled_from=prompt_text,
        prompt_digest=hashlib.sha256(prompt_text.encode("utf-8")).digest(),
    )


def _state(suite: AcceptanceSuite, intent_text: str | None) -> LoopState:
    return LoopState(
        plan=Plan(assumption="t8 test", confidence=1.0, steps=[]),
        workspace=WorkspaceSnapshot(),
        suite=suite,
        handshake_registry=HandshakeRegistry("."),
        budget=Budget(max_iterations=10),
        provider_timeout=ProviderTimeoutRecord(),
        current_intent_text=intent_text,
    )


# ---------------------------------------------------------------------------
# Enum-membership invariants
# ---------------------------------------------------------------------------


def test_t8_enum_member_present() -> None:
    """T8 must be a member of the closed TerminationCause vocabulary."""
    assert hasattr(TerminationCause, "PROMPT_DRIFT")
    assert TerminationCause.PROMPT_DRIFT.name == "PROMPT_DRIFT"


def test_t1_through_t9_all_present() -> None:
    """The closed vocabulary now covers nine causes (T1-T9).

    T9 (PROMPT_DIGEST_MISSING) landed in the module_04 SP Q4b
    amendment: opt-in strict mode fires it instead of skipping the
    check on pre-v0.5.1 suites.
    """
    expected = {
        "COMPLETE",
        "REGRESSED",
        "PROVENANCE_FAILURE",
        "ASSUMPTION_BURST",
        "BUDGET_EXHAUSTED",
        "HANDSHAKE_BLOCKED",
        "PROVIDER_TIMEOUT",
        "PROMPT_DRIFT",
        "PROMPT_DIGEST_MISSING",
    }
    actual = {member.name for member in TerminationCause}
    assert expected <= actual
    # Guard against accidental additions -- the reviewer should surface
    # them here so ADRs stay in sync.
    unexpected = actual - expected
    assert not unexpected, f"unexpected TerminationCause members: {unexpected}"


def test_enum_values_pinned() -> None:
    """SP Q1 amendment: enum values are pinned integers, not auto().

    Any reordering that shifts a member's integer value fails this
    test -- a serialised value from a v0.5.0 report must decode to
    the same TerminationCause on a v0.5.1 client.
    """
    expected_values = {
        "COMPLETE": 1,
        "REGRESSED": 2,
        "PROVENANCE_FAILURE": 3,
        "ASSUMPTION_BURST": 4,
        "BUDGET_EXHAUSTED": 5,
        "HANDSHAKE_BLOCKED": 6,
        "PROVIDER_TIMEOUT": 7,
        "PROMPT_DRIFT": 8,
        "PROMPT_DIGEST_MISSING": 9,
    }
    for name, value in expected_values.items():
        member = TerminationCause[name]
        assert member.value == value, (
            f"TerminationCause.{name} shifted to {member.value}; expected "
            f"{value}. Reordering the enum breaks cross-version "
            "serialisation."
        )


def test_check_t8_strict_mode_fires_t9_on_missing() -> None:
    """SP Q4b amendment: strict mode returns T9 instead of None."""
    predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(
            path="__never_present__", must_have_rootknot=False
        ),
        required=True,
    )
    legacy_suite = AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(predicate,),
        compiled_from="legacy",
    )  # prompt_digest=None
    assert (
        check_t8(legacy_suite, "anything", strict=True)
        is TerminationCause.PROMPT_DIGEST_MISSING
    )
    assert check_t8(legacy_suite, "anything", strict=False) is None


# ---------------------------------------------------------------------------
# check_t8 behaviour
# ---------------------------------------------------------------------------


def test_check_t8_match_returns_none() -> None:
    suite = _suite_with_prompt("write me a factorial")
    assert check_t8(suite, "write me a factorial") is None


def test_check_t8_mismatch_returns_t8() -> None:
    suite = _suite_with_prompt("write me a factorial")
    assert (
        check_t8(suite, "delete all files")
        is TerminationCause.PROMPT_DRIFT
    )


def test_check_t8_missing_digest_returns_none_backcompat() -> None:
    """Pre-v0.5.1 suites lack prompt_digest -- T8 must skip (backwards compat)."""
    predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(
            path="__never_present__", must_have_rootknot=False
        ),
        required=True,
    )
    legacy_suite = AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(predicate,),
        compiled_from="legacy prompt",
    )  # prompt_digest defaults to None
    assert check_t8(legacy_suite, "totally different") is None


def test_check_t8_byte_exact_only_whitespace_flip() -> None:
    """A single whitespace change flips the digest -- T8 must fire."""
    suite = _suite_with_prompt("write me a factorial")
    assert (
        check_t8(suite, "write me a  factorial")  # double space
        is TerminationCause.PROMPT_DRIFT
    )


# ---------------------------------------------------------------------------
# evaluate_termination dispatch
# ---------------------------------------------------------------------------


def test_evaluate_termination_fires_t8_when_current_intent_diverges() -> None:
    suite = _suite_with_prompt("write me a factorial")
    state = _state(suite, "delete all files")
    cause = evaluate_termination(state, now=0.0)
    assert cause is TerminationCause.PROMPT_DRIFT


def test_evaluate_termination_no_t8_when_intent_absent() -> None:
    """No ``current_intent_text`` on state => T8 branch is a no-op."""
    suite = _suite_with_prompt("write me a factorial")
    state = _state(suite, intent_text=None)
    # Budget not exhausted, no other cause fires; expected None.
    assert evaluate_termination(state, now=0.0) is None


def test_evaluate_termination_no_t8_when_intent_matches() -> None:
    suite = _suite_with_prompt("write me a factorial")
    state = _state(suite, "write me a factorial")
    assert evaluate_termination(state, now=0.0) is None


# ---------------------------------------------------------------------------
# Every existing switch/dispatch handles T8 (there is currently no
# runtime match; this test locks that invariant by scanning source).
# ---------------------------------------------------------------------------


def test_no_match_dispatch_omits_t8() -> None:
    """Guard: if a future module adds a match/switch on TerminationCause,
    every member (including PROMPT_DRIFT) must appear or the test fails.

    We scan ``src/ract/`` for the string ``match ... TerminationCause``
    or ``case TerminationCause.``; any match must cover PROMPT_DRIFT.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent / "src" / "ract"
    misses: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "case TerminationCause." not in text:
            continue
        # Every switch that names T1 must also name T8; this is a
        # coarse guard, refined per-file as switches are added.
        if "case TerminationCause.COMPLETE" in text and (
            "case TerminationCause.PROMPT_DRIFT" not in text
        ):
            misses.append(str(path.relative_to(root)))
    assert not misses, (
        "the following TerminationCause switches must add a "
        f"PROMPT_DRIFT case: {misses}"
    )
