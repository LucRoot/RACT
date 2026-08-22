"""Integration -- build_loop_state refuses when a verifier is unavailable.

v0.5.1 spec-completeness module_07 (Lens 2 Delta 2 closure). The
pre-check runs BEFORE any state is persisted or returned:
:func:`ract.core.loop.build_loop_state` asks
:meth:`AcceptancePredicate.available` for every REQUIRED predicate
and raises :class:`VerifierUnavailable` on the first miss, naming the
predicate id + verifier kind + specific reason.

Contract locked here:

1. AssertionInvocation with an unimportable callable_ref refuses loop
   entry.
2. The exception carries the failing predicate's id + verifier kind
   + a human-readable reason string.
3. Non-required predicates are exempt (the pre-check only walks the
   required set).
4. ``skip_verifier_availability_check=True`` bypasses the check
   (opt-in, for hermetic property tests / offline replay).
5. Availability of common verifiers (pytest / mypy / hypothesis)
   in the dev environment does NOT trip the check on healthy
   predicates -- backward-compat with existing tests using
   PytestInvocation / MypyInvocation / HypothesisInvocation.

Ox Alpha §2 SP mandatory Q4 answer: the check is STRUCTURAL
(refuses loop entry via raise), not advisory (WARN log). This test
proves the raise.
"""

from __future__ import annotations

import pytest

from ract.core.loop import WorkspaceSnapshot, build_loop_state
from ract.core.predicate import (
    AcceptancePredicate,
    AcceptanceSuite,
    AssertionInvocation,
    ArtifactInvocation,
    HypothesisInvocation,
    MypyInvocation,
    PytestInvocation,
    VerifierUnavailable,
    new_intent_id,
    new_predicate_id,
)
from ract.manager import Plan


# ---------------------------------------------------------------------------
# Helper callables for AssertionInvocation dispatches
# ---------------------------------------------------------------------------


def _always_true(_ws) -> bool:
    """Live callable_ref target for the "happy path" test."""
    return True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _make_plan() -> Plan:
    return Plan(assumption="test plan", confidence=1.0, steps=[])


def test_build_loop_state_refuses_when_assertion_callable_missing() -> None:
    """Loop entry refuses when a required AssertionInvocation targets an
    unimportable module.

    The raise carries the failing predicate's id + verifier kind
    + a reason naming the ImportError root cause. No suite.json
    write, no LoopState construction -- structurally halted at
    build_loop_state.
    """
    bad_predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="invariant",
        invocation=AssertionInvocation(
            callable_ref="nonexistent_module.that.does.not.exist:some_fn"
        ),
        required=True,
    )
    suite = AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(bad_predicate,),
    )
    with pytest.raises(VerifierUnavailable) as exc_info:
        build_loop_state(
            plan=_make_plan(),
            workspace=WorkspaceSnapshot(),
            suite=suite,
        )
    err = exc_info.value
    assert err.predicate_id == bad_predicate.id.hex(), (
        "VerifierUnavailable.predicate_id must name the failing "
        f"predicate (got {err.predicate_id!r})"
    )
    assert err.verifier == "invariant", "verifier field should carry the predicate kind"
    assert "nonexistent_module" in err.reason, (
        f"reason must name the specific failure: got {err.reason!r}"
    )


def test_build_loop_state_names_first_unavailable_verifier() -> None:
    """When multiple predicates fail availability, the first one raises.

    The pre-check walks the required list in order; the first miss
    halts. Predicates AFTER the miss are not evaluated (defensive:
    a diagnostics tool can then rerun with the fix in place).
    """
    bad1 = AcceptancePredicate(
        id=new_predicate_id(),
        kind="invariant",
        invocation=AssertionInvocation(callable_ref="broken.module.one:fn"),
        required=True,
    )
    bad2 = AcceptancePredicate(
        id=new_predicate_id(),
        kind="invariant",
        invocation=AssertionInvocation(callable_ref="broken.module.two:fn"),
        required=True,
    )
    suite = AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(bad1, bad2),
    )
    with pytest.raises(VerifierUnavailable) as exc_info:
        build_loop_state(
            plan=_make_plan(),
            workspace=WorkspaceSnapshot(),
            suite=suite,
        )
    assert exc_info.value.predicate_id == bad1.id.hex()


def test_build_loop_state_ignores_non_required_predicate() -> None:
    """A non-required predicate with an unavailable verifier does NOT
    refuse loop entry.

    The pre-check walks ``suite.required()`` only. A required
    predicate whose verifier is available paired with a non-required
    predicate whose verifier is missing lands in a valid LoopState.
    """
    ok_predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="invariant",
        invocation=AssertionInvocation(
            callable_ref=(
                "tests.integration.test_verifier_availability_precheck:_always_true"
            )
        ),
        required=True,
    )
    bad_optional = AcceptancePredicate(
        id=new_predicate_id(),
        kind="invariant",
        invocation=AssertionInvocation(callable_ref="does.not.exist:x"),
        required=False,
    )
    suite = AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(ok_predicate, bad_optional),
    )
    state = build_loop_state(
        plan=_make_plan(),
        workspace=WorkspaceSnapshot(),
        suite=suite,
    )
    assert state is not None
    assert state.suite is suite


def test_build_loop_state_opt_out_bypasses_check() -> None:
    """``skip_verifier_availability_check=True`` bypasses the pre-check.

    Opt-out is the ONLY documented escape hatch (hermetic property
    tests / offline replay); a silent WARN log would defeat the
    pre-check purpose per Ox Alpha SP Q4.
    """
    bad_predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="invariant",
        invocation=AssertionInvocation(callable_ref="nonexistent:fn"),
        required=True,
    )
    suite = AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(bad_predicate,),
    )
    state = build_loop_state(
        plan=_make_plan(),
        workspace=WorkspaceSnapshot(),
        suite=suite,
        skip_verifier_availability_check=True,
    )
    assert state is not None


def _raising_from_getattr(_ws) -> bool:
    """Intentional raise for the unexpected-exception amendment test."""
    raise TypeError("simulated unexpected exception from callable resolution")


class _CrashingAvailableProxy:
    """Wraps AcceptancePredicate to force ``available()`` to raise a
    non-caught exception type, exercising the SP amendment
    (Ox Alpha + cross-family second reviewer D1 converged DEFECT fix).
    """

    def __init__(self, predicate: AcceptancePredicate) -> None:
        self._wrapped = predicate
        self.id = predicate.id
        self.kind = predicate.kind
        self.required = predicate.required

    def available(self) -> tuple[bool, str]:
        # Simulate a non-caught exception path from _resolve_callable
        # (e.g. TypeError from module-level __getattr__, MemoryError,
        # or a custom exception class).
        raise RuntimeError("simulated availability-check crash")

    def evaluate(self, ws):  # pragma: no cover - not reached
        return self._wrapped.evaluate(ws)


def test_available_check_crash_converts_to_verifier_unavailable() -> None:
    """SP amendment: an unexpected exception from ``available()``
    (i.e. NOT in the closed catch list ``ImportError`` /
    ``AttributeError`` / ``ValueError``) is CONVERTED to
    :class:`VerifierUnavailable` with a reason that carries the
    original exception class + message.

    Regression anchor for the Ox Alpha + cross-family second reviewer D1 converged
    DEFECT: prior behavior propagated the raw exception, violating
    the documented "raise VerifierUnavailable" structural refusal
    contract. Callers catching only :class:`VerifierUnavailable`
    would see an untyped crash instead of a structured refusal.
    """
    ok_pred = AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(path="README.md"),
        required=True,
    )
    crashing = _CrashingAvailableProxy(ok_pred)

    class _FakeSuite:
        intent_id = new_intent_id()
        predicates = (crashing,)

        def required(self):
            return (crashing,)

    with pytest.raises(VerifierUnavailable) as exc_info:
        build_loop_state(
            plan=_make_plan(),
            workspace=WorkspaceSnapshot(),
            suite=_FakeSuite(),
        )
    err = exc_info.value
    assert err.predicate_id == ok_pred.id.hex()
    assert "availability check crashed" in err.reason
    assert "RuntimeError" in err.reason
    assert "simulated availability-check crash" in err.reason


def test_build_loop_state_admits_healthy_predicates() -> None:
    """PytestInvocation + MypyInvocation + HypothesisInvocation +
    ArtifactInvocation + healthy AssertionInvocation compose cleanly.

    Backward-compat guard: the pre-check must not break existing
    tests that construct suites with these invocations. The dev
    environment (per ``pyproject.toml`` dev deps) has pytest, mypy,
    and hypothesis installed.
    """
    ok_predicates = (
        AcceptancePredicate(
            id=new_predicate_id(),
            kind="test",
            invocation=PytestInvocation(selector="tests/test_x.py::test_ok"),
            required=True,
        ),
        AcceptancePredicate(
            id=new_predicate_id(),
            kind="type",
            invocation=MypyInvocation(target="src/ract"),
            required=True,
        ),
        AcceptancePredicate(
            id=new_predicate_id(),
            kind="property",
            invocation=HypothesisInvocation(target="ract.core.predicate:roundtrip"),
            required=True,
        ),
        AcceptancePredicate(
            id=new_predicate_id(),
            kind="artifact",
            invocation=ArtifactInvocation(path="README.md"),
            required=True,
        ),
        AcceptancePredicate(
            id=new_predicate_id(),
            kind="invariant",
            invocation=AssertionInvocation(
                callable_ref=(
                    "tests.integration.test_verifier_availability_precheck:_always_true"
                )
            ),
            required=True,
        ),
    )
    suite = AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=ok_predicates,
    )
    state = build_loop_state(
        plan=_make_plan(),
        workspace=WorkspaceSnapshot(),
        suite=suite,
    )
    assert state is not None
    assert len(state.suite.required()) == 5


# RACT 0.5.1
