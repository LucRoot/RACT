"""Tests for the compiled acceptance suite (module_01 of the v0.4 substrate).

SUBSTRATE spec §2 and §11 signals 1 and 2 govern the design; the failure
mode this file exists to prevent is the model grading its own homework.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import FrozenInstanceError

import pytest

from ract.core.compile import CompilerInputs, IntentCompiler
from ract.core.loop import (
    LoopState,
    QualityScore,
    TerminationCause,
    WorkspaceSnapshot,
    build_loop_state,
    check_t1,
    check_t2,
    evaluate_termination,
)
from ract.core.predicate import (
    AcceptancePredicate,
    AcceptanceSuite,
    ArtifactInvocation,
    AssertionInvocation,
    HypothesisInvocation,
    MypyInvocation,
    PredicateResult,
    PytestInvocation,
    new_intent_id,
    new_predicate_id,
    suite_from_canonical,
    suite_from_json,
)
from ract.handshake_registry import HandshakeRegistry
from ract.manager import Plan


# ---------------------------------------------------------------------------
# helpers used by AssertionInvocation callable_refs
# ---------------------------------------------------------------------------


def always_false(_ws: WorkspaceSnapshot) -> bool:
    """Invariant callable that always returns False.

    Referenced by ``test_worked_example_model_votes_done_environment_refuses``
    via a dotted ``callable_ref`` on ``AssertionInvocation``.
    """
    return False


# ---------------------------------------------------------------------------
# Local factories keep the tests readable and independent of the compiler.
# ---------------------------------------------------------------------------


def _artifact_predicate(path: str, *, required: bool = True) -> AcceptancePredicate:
    return AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(path=path, must_have_rootknot=False),
        required=required,
    )


def _mk_suite(preds: list[AcceptancePredicate]) -> AcceptanceSuite:
    return AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=tuple(preds),
        compiled_from="test intent",
    )


# ---------------------------------------------------------------------------
# 1. Suite freezes on construction
# ---------------------------------------------------------------------------


def test_suite_freezes_before_loop_entry():
    """A frozen suite refuses field reassignment; the predicate tuple is immutable."""
    suite = _mk_suite([_artifact_predicate("a.py")])
    # Reassigning a frozen dataclass field raises FrozenInstanceError.
    with pytest.raises(FrozenInstanceError):
        suite.predicates = ()  # type: ignore[misc]
    # The tuple itself has no ``append`` — mutating the container would raise
    # AttributeError. This is the belt to the frozen-dataclass suspenders.
    with pytest.raises(AttributeError):
        suite.predicates.append(_artifact_predicate("b.py"))  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 2. T1 requires all required predicates to pass
# ---------------------------------------------------------------------------


def test_t1_requires_all_required_predicates_pass():
    """Two required + one optional: T1 fires only when both required pass."""
    p1 = _artifact_predicate("a.py", required=True)
    p2 = _artifact_predicate("b.py", required=True)
    p3 = _artifact_predicate("c.py", required=False)
    suite = _mk_suite([p1, p2, p3])

    # Only the optional predicate is satisfied.
    ws_partial = WorkspaceSnapshot(files={"c.py": ""})
    assert check_t1(suite, ws_partial) is None

    # Only one of the two required predicates is satisfied.
    ws_one = WorkspaceSnapshot(files={"a.py": "", "c.py": ""})
    assert check_t1(suite, ws_one) is None

    # Both required predicates are satisfied → COMPLETE.
    ws_both = WorkspaceSnapshot(files={"a.py": "", "b.py": "", "c.py": ""})
    assert check_t1(suite, ws_both) is TerminationCause.COMPLETE


# ---------------------------------------------------------------------------
# 3. ProgressOracle cannot terminate T1
# ---------------------------------------------------------------------------


def test_progress_oracle_cannot_terminate_t1(tmp_path):
    """A model-authored oracle verdict cannot bypass a failing predicate.

    Even if a scheduling heuristic returned score=1.0, T1 reads the suite;
    a failing required predicate keeps ``evaluate_termination`` from
    returning ``COMPLETE``.
    """
    p1 = _artifact_predicate("missing.py", required=True)
    suite = _mk_suite([p1])
    state = LoopState(
        plan=Plan(assumption="test", confidence=1.0, steps=[]),
        workspace=WorkspaceSnapshot(files={}),
        suite=suite,
        handshake_registry=HandshakeRegistry(tmp_path),
    )
    # Even if we blast the quality history with perfect scores, T1 doesn't fire.
    state.quality_history = [QualityScore(value=1.0, iteration=i) for i in range(3)]
    cause = evaluate_termination(state, now=0.0)
    assert cause is not TerminationCause.COMPLETE


# ---------------------------------------------------------------------------
# 4. ProgressOracle still drives T2 (regression)
# ---------------------------------------------------------------------------


def test_progress_oracle_still_drives_t2():
    """T2 continues to read ``quality_history``; the downgrade does not remove it."""
    history = [
        QualityScore(value=0.9, iteration=1),
        QualityScore(value=0.7, iteration=2),
        QualityScore(value=0.5, iteration=3),
    ]
    assert check_t2(history, delta_regress=0.1) is TerminationCause.REGRESSED


# ---------------------------------------------------------------------------
# 5. Suite is written before the first step executes
# ---------------------------------------------------------------------------


def test_suite_written_before_first_step(tmp_path):
    """``build_loop_state`` writes ``suite.json`` before returning to the caller.

    The fake executor records the order of filesystem operations, so the
    assertion is not just "the file exists" but "the file exists before the
    first step-write path could have run."
    """
    order: list[str] = []

    class FakeStepExecutor:
        def __init__(self, run_dir):
            self.run_dir = run_dir

        def run(self):
            order.append("step_executed")
            (self.run_dir / "step_output.txt").write_text("done", encoding="utf-8")

    run_dir = tmp_path / "evals" / "runs" / "run-abc"

    p1 = _artifact_predicate("hello.py", required=True)
    suite = _mk_suite([p1])

    # The suite must be on disk *before* the LoopState is handed back.
    _state = build_loop_state(
        plan=Plan(assumption="t", confidence=1.0, steps=[]),
        workspace=WorkspaceSnapshot(),
        suite=suite,
        run_dir=run_dir,
    )
    order.append("build_loop_state_returned")

    suite_path = run_dir / "suite.json"
    assert suite_path.is_file()
    # No step has executed yet.
    assert "step_executed" not in order

    executor = FakeStepExecutor(run_dir)
    executor.run()
    assert order == ["build_loop_state_returned", "step_executed"]

    # The persisted form is canonical JSON with the expected version.
    payload = json.loads(suite_path.read_text(encoding="utf-8"))
    assert payload["compiler_version"] == "0.4.0"
    # Round-trip: canonical JSON → suite → same digest.
    round_tripped = suite_from_json(suite_path.read_text(encoding="utf-8"))
    assert round_tripped.digest() == suite.digest()
    # Reader dispatch: an unknown version is refused.
    with pytest.raises(ValueError, match="unknown compiler_version"):
        suite_from_canonical({**payload, "compiler_version": "9.9.9"})


# ---------------------------------------------------------------------------
# 6. Worked example: model would vote done, environment refuses
# ---------------------------------------------------------------------------


def test_worked_example_model_votes_done_environment_refuses(tmp_path):
    """Synthetic run: a required invariant predicate returns False → not COMPLETE."""
    invariant = AcceptancePredicate(
        id=new_predicate_id(),
        kind="invariant",
        invocation=AssertionInvocation(
            callable_ref="test_acceptance_suite:always_false"
        ),
        required=True,
    )
    suite = _mk_suite([invariant])
    state = LoopState(
        plan=Plan(assumption="t", confidence=1.0, steps=[]),
        workspace=WorkspaceSnapshot(),
        suite=suite,
        handshake_registry=HandshakeRegistry(tmp_path),
    )
    # A model would call this "done"; the environment sees the required
    # invariant returning False and refuses COMPLETE.
    cause = evaluate_termination(state, now=0.0)
    assert cause is not TerminationCause.COMPLETE


# ---------------------------------------------------------------------------
# 7. New-test predicates require a handshake before they enter the suite
# ---------------------------------------------------------------------------


def test_new_test_predicates_require_handshake(tmp_path):
    """A proposed new test blocks on ``HandshakeRegistry`` until approved.

    The compiler groups proposals by kind (lateral chain branch A) so the
    operator resolves one handshake per group; until that group is
    approved, the proposed predicates do not enter the frozen suite.
    """
    approvals = HandshakeRegistry(tmp_path)
    compiler = IntentCompiler()
    ws = WorkspaceSnapshot(
        files={
            "tests/test_existing.py": "def test_a(): pass\n",
        }
    )
    inputs = CompilerInputs(
        proposed_new_tests=("tests/test_new.py::test_new_case",),
        touched_surface=("src/mymodule.py",),
        invariant_callables=("test_acceptance_suite:always_false",),
    )
    suite = compiler.compile(
        intent_text="add a new feature", ws=ws, approvals=approvals, inputs=inputs
    )

    # The proposed selector never enters the frozen suite before approval.
    selectors = [
        p.invocation.selector
        for p in suite.predicates
        if isinstance(p.invocation, PytestInvocation)
    ]
    assert "tests/test_new.py::test_new_case" not in selectors

    # A single grouped handshake is pending for the 'test' group.
    pending = approvals.pending()
    assert any(item.id == "acceptance.compiler.group.test" for item in pending)
    # The handshake carries a diff-shaped preview.
    test_handshake = next(
        item for item in pending if item.id == "acceptance.compiler.group.test"
    )
    assert "+++ acceptance/test" in test_handshake.acceptance
    assert "+ tests/test_new.py::test_new_case" in test_handshake.acceptance

    # Once the operator approves the group, a re-compile lands the predicate.
    approvals.update_status("acceptance.compiler.group.test", "approved")
    suite2 = compiler.compile(
        intent_text="add a new feature", ws=ws, approvals=approvals, inputs=inputs
    )
    selectors2 = [
        p.invocation.selector
        for p in suite2.predicates
        if isinstance(p.invocation, PytestInvocation)
    ]
    assert "tests/test_new.py::test_new_case" in selectors2


# ---------------------------------------------------------------------------
# Guardrails on the LoopState constructor (lateral chain branch B)
# ---------------------------------------------------------------------------


def test_zero_required_predicate_suite_is_refused_at_loop_entry(tmp_path):
    """A suite with only optional predicates has T1 trivially never fire.

    The loop constructor refuses it with a specific error naming the intent,
    per lateral chain branch B.
    """
    optional = _artifact_predicate("a.py", required=False)
    suite = _mk_suite([optional])
    with pytest.raises(ValueError, match="zero required predicates"):
        LoopState(
            plan=Plan(assumption="t", confidence=1.0, steps=[]),
            workspace=WorkspaceSnapshot(),
            suite=suite,
            handshake_registry=HandshakeRegistry(tmp_path),
        )


# ---------------------------------------------------------------------------
# Metadata-channel evaluators return the recorded outcome verbatim
# ---------------------------------------------------------------------------


def test_metadata_channel_evaluators_read_snapshot_recorded_results():
    """pytest, mypy, hypothesis evaluators are pure over the metadata channel."""
    pytest_pred = AcceptancePredicate(
        id=new_predicate_id(),
        kind="test",
        invocation=PytestInvocation(selector="tests/test_x.py::test_ok"),
        required=True,
    )
    mypy_pred = AcceptancePredicate(
        id=new_predicate_id(),
        kind="type",
        invocation=MypyInvocation(target="src/ract"),
        required=True,
    )
    hypo_pred = AcceptancePredicate(
        id=new_predicate_id(),
        kind="property",
        invocation=HypothesisInvocation(target="ract.core.predicate:roundtrip"),
        required=True,
    )
    ws_ok = WorkspaceSnapshot(
        metadata={
            "pytest": {
                "tests/test_x.py::test_ok": {"ok": True, "reason": "passed"}
            },
            "mypy": {"src/ract": {"ok": True, "reason": "no issues"}},
            "hypothesis": {
                "ract.core.predicate:roundtrip": {"ok": True, "reason": "50 examples"}
            },
        }
    )
    assert isinstance(pytest_pred.evaluate(ws_ok), PredicateResult)
    assert pytest_pred.evaluate(ws_ok).ok is True
    assert mypy_pred.evaluate(ws_ok).ok is True
    assert hypo_pred.evaluate(ws_ok).ok is True

    # Absent metadata means "unresolved", which is ok=False, not a silent pass.
    ws_empty = WorkspaceSnapshot()
    assert pytest_pred.evaluate(ws_empty).ok is False
    assert mypy_pred.evaluate(ws_empty).ok is False
    assert hypo_pred.evaluate(ws_empty).ok is False


def test_artifact_predicate_requires_sidecar_when_flag_set():
    """``must_have_rootknot=True`` requires the ``.<name>.rootknot.json`` sidecar."""
    predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(path="src/foo.py", must_have_rootknot=True),
        required=True,
    )
    ws_missing_sidecar = WorkspaceSnapshot(files={"src/foo.py": ""})
    assert predicate.evaluate(ws_missing_sidecar).ok is False

    ws_with_sidecar = WorkspaceSnapshot(
        files={
            "src/foo.py": "",
            "src/.foo.py.rootknot.json": "{}",
        }
    )
    assert predicate.evaluate(ws_with_sidecar).ok is True


# ---------------------------------------------------------------------------
# Suite invariants: id uniqueness, canonical serialization stability
# ---------------------------------------------------------------------------


def test_suite_rejects_duplicate_predicate_ids():
    fixed_id = uuid.uuid4().bytes
    p1 = AcceptancePredicate(
        id=fixed_id,
        kind="artifact",
        invocation=ArtifactInvocation(path="a.py"),
        required=True,
    )
    p2 = AcceptancePredicate(
        id=fixed_id,
        kind="artifact",
        invocation=ArtifactInvocation(path="b.py"),
        required=True,
    )
    with pytest.raises(ValueError, match="duplicate predicate id"):
        AcceptanceSuite(
            intent_id=new_intent_id(), predicates=(p1, p2), compiled_from="dup"
        )


def test_suite_digest_is_stable_across_serialization():
    p1 = _artifact_predicate("a.py")
    p2 = _artifact_predicate("b.py")
    suite = _mk_suite([p1, p2])
    text = suite.to_json()
    round_tripped = suite_from_json(text)
    assert round_tripped.digest() == suite.digest()


# RACT 0.4.0
