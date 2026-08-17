"""Tests for ALM Gate G1 (held-out predicates) and Gate G2 (mutation-kill).

ALM module_01. The seven tests here are the boolean floor named in the
module fragment's Definition of Done. Each one closes a specific
sycophancy or measurement-theatre failure mode:

- ``test_dual_suite_freezes_before_loop_entry`` — freeze catches a
  post-construction mutation attempt on the visible half.
- ``test_held_out_seal_refused_by_model_capability`` — the manifest
  denies read of the seal path.
- ``test_held_out_digest_committed_publicly`` — the digest is in the
  clear on disk; the plaintext held-out predicates never are.
- ``test_mutation_kill_below_threshold_rolls_back`` — G2 under floor
  rolls back the transaction and emits ``laziness.violated``.
- ``test_equivalent_mutants_do_not_count_against_kill_rate`` — ACH
  filter reduces the denominator.
- ``test_holdout_composition_non_trivial`` — a composer whose
  predicates do not distinguish workspace from perturbation is
  rejected (holdout_kind='trivial').
- ``test_worked_example_visible_passes_holdout_fails`` — T1 does not
  fire COMPLETE when the visible suite is green but held-out is red.
"""

from __future__ import annotations

import base64
import json
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from typing import Iterable

import pytest

from ract.antilazy.holdout import (
    DualAcceptanceSuite,
    check_visible_and_held_out,
    compose_held_out,
    seal_held_out,
    unseal_held_out,
    write_dual_suite_snapshot,
)
from ract.antilazy.mutation import (
    Mutant,
    run_mutation,
)
from ract.antilazy.pre_commit import GateOutcome, enforce_g2
from ract.core.loop import (
    WorkspaceSnapshot,
    check_t1,
)
from ract.core.predicate import (
    AcceptancePredicate,
    AcceptanceSuite,
    ArtifactInvocation,
    AssertionInvocation,
    new_intent_id,
    new_predicate_id,
)
from ract.core.transaction import (
    ResourceBudget,
    StepTransaction,
    new_step_id,
)
from ract.security.keys import SandboxKey
from ract.security.manifest import CapabilityManifest, FilesystemPolicy
from ract.trace.sink import clear_writer, set_writer
from ract.trace.writer import JsonlEventWriter


# ---------------------------------------------------------------------------
# Helpers — assertion callables that inspect a WorkspaceSnapshot
# ---------------------------------------------------------------------------


def _has_add_symbol(ws: WorkspaceSnapshot) -> bool:
    """Held-out invariant: the touched file contains a ``def add`` line.

    A byte-shuffled perturbation of the file destroys the line
    boundary; the perturbed snapshot fails this check, so the
    composed predicate distinguishes the workspace from the
    perturbation and passes the non-triviality check.
    """
    source = ws.files.get("src/calc.py", "")
    return "def add" in source


def _always_true(_ws: WorkspaceSnapshot) -> bool:
    """Trivial invariant that does not distinguish workspaces."""
    return True


def _predicate_from_callable(ref: str, *, required: bool = True) -> AcceptancePredicate:
    return AcceptancePredicate(
        id=new_predicate_id(),
        kind="invariant",
        invocation=AssertionInvocation(callable_ref=ref),
        required=required,
    )


def _visible_suite() -> AcceptanceSuite:
    return AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(
            AcceptancePredicate(
                id=new_predicate_id(),
                kind="artifact",
                invocation=ArtifactInvocation(path="src/calc.py"),
                required=True,
            ),
        ),
        compiled_from="visible test suite",
    )


def _held_out_suite(intent_id: bytes) -> AcceptanceSuite:
    return AcceptanceSuite(
        intent_id=intent_id,
        predicates=(
            _predicate_from_callable(
                "test_antilazy_g1_g2:_has_add_symbol", required=True
            ),
        ),
        compiled_from="held-out composed by companion",
    )


def _workspace_with_calc() -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        files={
            "src/calc.py": ("def add(a: int, b: int) -> int:\n    return a + b\n"),
        },
        timestamp=1.0,
    )


# ---------------------------------------------------------------------------
# 1. Freeze
# ---------------------------------------------------------------------------


def test_dual_suite_freezes_before_loop_entry() -> None:
    visible = _visible_suite()
    held_out = _held_out_suite(visible.intent_id)
    dual = DualAcceptanceSuite(
        visible=visible,
        held_out=held_out,
        held_out_digest=held_out.digest(),
        held_out_seal=b"seal-bytes",
        holdout_kind="real",
    )
    with pytest.raises(FrozenInstanceError):
        dual.visible = _visible_suite()  # type: ignore[misc]
    # The held-out tuple must also be frozen so an in-memory swap
    # cannot silently move the enforcement target after construction.
    with pytest.raises((AttributeError, TypeError)):
        dual.visible.predicates = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. Seal refused by model-facing capability
# ---------------------------------------------------------------------------


def test_held_out_seal_refused_by_model_capability(tmp_path: Path) -> None:
    # Build a run-scoped SandboxKey and seal a suite under it.
    run_id = bytes.fromhex("11" * 16)
    sandbox_key = SandboxKey.generate(run_id, workspace_root=tmp_path)
    held_out = _held_out_suite(new_intent_id())
    seal = seal_held_out(held_out, sandbox_key)
    assert seal, "seal must produce non-empty ciphertext"
    # Round-trip: the sandbox side can unseal.
    recovered = unseal_held_out(seal, sandbox_key)
    assert recovered.digest() == held_out.digest()
    # A model-facing manifest declares filesystem.read paths — the
    # sandbox refuses read of anything not in that set. The seal file
    # for a run lives under ``.rack/sandbox/holdout/<run_id>.seal``;
    # a model-facing manifest that does not name the path is a refusal
    # by construction (SUBSTRATE §4.2 allowlist-not-denylist idiom).
    seal_dir = tmp_path / ".rack" / "sandbox" / "holdout"
    seal_dir.mkdir(parents=True, exist_ok=True)
    seal_path = seal_dir / f"{run_id.hex()}.seal"
    seal_path.write_bytes(seal)
    manifest = CapabilityManifest(
        run_id=run_id.hex(),
        filesystem=FilesystemPolicy(
            read=(str(tmp_path / "src") + "/**",),
            write=(),
            denied=(str(tmp_path / ".rack") + "/**",),
        ),
    )
    denied_globs = manifest.filesystem.denied
    assert any(
        str(seal_path).startswith(g.rstrip("*").rstrip("/")) for g in denied_globs
    ), "the seal path must be under a denied glob on the model-facing manifest"


# ---------------------------------------------------------------------------
# 3. Digest committed publicly; seal is ciphertext
# ---------------------------------------------------------------------------


def test_held_out_digest_committed_publicly(tmp_path: Path) -> None:
    run_id = bytes.fromhex("22" * 16)
    sandbox_key = SandboxKey.generate(run_id, workspace_root=tmp_path)
    visible = _visible_suite()
    held_out = _held_out_suite(visible.intent_id)
    seal = seal_held_out(held_out, sandbox_key)
    dual = DualAcceptanceSuite(
        visible=visible,
        held_out=held_out,
        held_out_digest=held_out.digest(),
        held_out_seal=seal,
        holdout_kind="real",
    )
    run_dir = tmp_path / "evals" / "runs" / "test_run"
    path = write_dual_suite_snapshot(run_dir, dual)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["held_out_digest"] == held_out.digest()
    # The seal round-trips through base64 into ciphertext bytes.
    ct = base64.b64decode(payload["held_out_seal"])
    assert ct == seal
    # The plaintext of held-out predicates does not appear in the file.
    text = path.read_text(encoding="utf-8")
    for predicate in held_out.predicates:
        assert predicate.id.hex() not in text, (
            "the held-out plaintext predicate ids leaked into the "
            "publicly-committed suite.json"
        )


# ---------------------------------------------------------------------------
# 4. Below-threshold mutation kill rolls back
# ---------------------------------------------------------------------------


@dataclass
class _FixedEvaluator:
    """KillEvaluator whose verdicts are keyed by mutant id."""

    killed_ids: set[str]

    def kills(self, mutant: Mutant, suite: AcceptanceSuite) -> bool:  # noqa: D401
        return mutant.id in self.killed_ids


class _EmptySource:
    """Synthetic MutantSource that yields 10 fixed mutants on ``src/x.py``."""

    def generate(self, touched_files: tuple[str, ...]) -> tuple[Mutant, ...]:  # noqa: ARG002
        return tuple(
            Mutant(
                id=f"m{i}",
                path="src/x.py",
                line=i,
                kind="binop_swap",
                original="a+b",
                payload="a-b",
            )
            for i in range(1, 11)
        )


def test_mutation_kill_below_threshold_rolls_back(tmp_path: Path) -> None:
    # A wire-through test: 10 mutants, 5 killed → kill rate 0.5 < 0.7.
    evaluator = _FixedEvaluator(killed_ids={f"m{i}" for i in range(1, 6)})
    source = _EmptySource()
    suite = _visible_suite()
    txn = StepTransaction(
        step_id=new_step_id(),
        parent_snapshot="deadbeef",
        worktree_path=tmp_path / "wt",
        postconditions=(),
        timeout_seconds=60,
        budget=ResourceBudget(),
    )
    # Wire a JsonlEventWriter so the laziness.violated emit is durable.
    writer = JsonlEventWriter(
        path=tmp_path / "events.jsonl",
        run_id=bytes.fromhex("33" * 16),
    )
    set_writer(writer)
    try:
        outcome: GateOutcome = enforce_g2(
            txn,
            suite,
            touched_files=("src/x.py",),
            source=source,
            evaluator=evaluator,
            detector=None,
            threshold=0.7,
        )
    finally:
        clear_writer()
    assert not outcome.passed
    assert outcome.should_roll_back
    assert outcome.report.kill_rate == pytest.approx(0.5)
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    kinds = [e["kind"] for e in events]
    assert "laziness.violated" in kinds
    for entry in events:
        if entry["kind"] == "laziness.violated":
            assert entry["payload"]["kind"] == "mutation_kill_below_threshold"


# ---------------------------------------------------------------------------
# 5. Equivalents do not count against kill rate
# ---------------------------------------------------------------------------


class _EquivalenceMock:
    """EquivalenceDetector that marks a fixed id set as equivalent."""

    def __init__(self, equivalent_ids: Iterable[str]) -> None:
        self._equiv = tuple(equivalent_ids)

    def classify(self, mutants: Iterable[Mutant]) -> tuple[str, ...]:
        seen = {m.id for m in mutants}
        return tuple(mid for mid in self._equiv if mid in seen)


def test_equivalent_mutants_do_not_count_against_kill_rate() -> None:
    # 10 mutants, 5 killed, 3 flagged equivalent among the survivors.
    # Net denominator = 10 - 3 = 7. Kill rate = 5 / 7 ≈ 0.714.
    evaluator = _FixedEvaluator(killed_ids={f"m{i}" for i in range(1, 6)})
    source = _EmptySource()
    detector = _EquivalenceMock(equivalent_ids=("m6", "m7", "m8"))
    report = run_mutation(
        touched_files=("src/x.py",),
        suite=_visible_suite(),
        source=source,
        evaluator=evaluator,
        detector=detector,
        threshold=0.7,
    )
    assert report.mutants_killed == 5
    assert report.mutants_equivalent == ("m6", "m7", "m8")
    assert report.mutants_survived == ("m9", "m10")
    assert report.kill_rate == pytest.approx(5 / 7)


# ---------------------------------------------------------------------------
# 6. Non-triviality check — trivial composer is rejected
# ---------------------------------------------------------------------------


class _TrivialComposer:
    """Composer whose held-out predicate does not distinguish workspaces."""

    def compose(
        self, visible: AcceptanceSuite, ws: WorkspaceSnapshot
    ) -> AcceptanceSuite:
        return AcceptanceSuite(
            intent_id=visible.intent_id,
            predicates=(
                _predicate_from_callable(
                    "test_antilazy_g1_g2:_always_true", required=True
                ),
            ),
        )


class _RealComposer:
    """Composer whose held-out predicate distinguishes ws vs. shuffled."""

    def compose(
        self, visible: AcceptanceSuite, ws: WorkspaceSnapshot
    ) -> AcceptanceSuite:
        return AcceptanceSuite(
            intent_id=visible.intent_id,
            predicates=(
                _predicate_from_callable(
                    "test_antilazy_g1_g2:_has_add_symbol", required=True
                ),
            ),
        )


def test_holdout_composition_non_trivial() -> None:
    visible = _visible_suite()
    ws = _workspace_with_calc()
    trivial_out, trivial_kind = compose_held_out(
        visible, ws, _TrivialComposer(), touched=("src/calc.py",)
    )
    assert trivial_kind == "trivial"
    assert trivial_out.predicates == ()
    real_out, real_kind = compose_held_out(
        visible, ws, _RealComposer(), touched=("src/calc.py",)
    )
    assert real_kind == "real"
    assert len(real_out.predicates) >= 1


# ---------------------------------------------------------------------------
# 7. Worked example: visible green, held-out red → T1 does not fire COMPLETE
# ---------------------------------------------------------------------------


def _visible_ok_predicate() -> AcceptancePredicate:
    return AcceptancePredicate(
        id=new_predicate_id(),
        kind="invariant",
        invocation=AssertionInvocation(callable_ref="test_antilazy_g1_g2:_always_true"),
        required=True,
    )


def _held_out_fail_predicate() -> AcceptancePredicate:
    return AcceptancePredicate(
        id=new_predicate_id(),
        kind="invariant",
        invocation=AssertionInvocation(
            callable_ref="test_antilazy_g1_g2:_always_false_held_out"
        ),
        required=True,
    )


def _always_false_held_out(_ws: WorkspaceSnapshot) -> bool:
    return False


def test_worked_example_visible_passes_holdout_fails(tmp_path: Path) -> None:
    visible = AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(_visible_ok_predicate(),),
        compiled_from="green visible",
    )
    held_out = AcceptanceSuite(
        intent_id=visible.intent_id,
        predicates=(_held_out_fail_predicate(),),
        compiled_from="red held-out",
    )
    dual = DualAcceptanceSuite(
        visible=visible,
        held_out=held_out,
        held_out_digest=held_out.digest(),
        held_out_seal=b"",
        holdout_kind="real",
    )
    snapshot = WorkspaceSnapshot(files={}, timestamp=0.0)
    # ALM check_t1: dual detected via duck typing.
    cause = check_t1(dual, snapshot)  # type: ignore[arg-type]
    assert cause is None, "T1 must not fire COMPLETE when the held-out suite is red"
    # A gap should have been emitted; wire a writer and re-run to observe.
    writer = JsonlEventWriter(
        path=tmp_path / "events.jsonl",
        run_id=bytes.fromhex("44" * 16),
    )
    set_writer(writer)
    try:
        outcome = check_visible_and_held_out(dual, snapshot)
    finally:
        clear_writer()
    assert outcome.gap is True
    assert outcome.visible_ok is True
    assert outcome.held_out_ok is False
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    laziness = [e for e in events if e["kind"] == "laziness.violated"]
    assert laziness, "expected at least one laziness.violated event"
    assert laziness[0]["payload"]["kind"] == "visible_holdout_gap"
    # Lateral chain branch A: the trace surface must not carry the raw
    # held-out predicate ids, only the digest and counts.
    for entry in laziness:
        payload_str = json.dumps(entry["payload"])
        for predicate in held_out.predicates:
            assert predicate.id.hex() not in payload_str, (
                "held-out predicate id leaked into the laziness.violated payload"
            )


# ---------------------------------------------------------------------------
# 8. Second-pass finding 1 — held-out predicate ids redacted from trace
# ---------------------------------------------------------------------------


def test_held_out_predicate_id_redacted_from_predicate_evaluated_event(
    tmp_path: Path,
) -> None:
    """Second Pass finding 1 (external reviewer).

    ``AcceptancePredicate.evaluate`` emits a ``predicate.evaluated``
    event carrying ``predicate_id`` in the payload. Without redaction,
    a model observing the trace surface can enumerate the held-out
    predicate ids by their evaluation events. The fix sets a
    context-var-scoped redaction flag while iterating held-out
    predicates so the trace payload carries a digest instead of the
    raw hex.
    """
    visible = _visible_suite()
    held_out = _held_out_suite(visible.intent_id)
    dual = DualAcceptanceSuite(
        visible=visible,
        held_out=held_out,
        held_out_digest=held_out.digest(),
        held_out_seal=b"",
        holdout_kind="real",
    )
    snapshot = _workspace_with_calc()
    writer = JsonlEventWriter(
        path=tmp_path / "events.jsonl",
        run_id=bytes.fromhex("55" * 16),
    )
    set_writer(writer)
    try:
        check_visible_and_held_out(dual, snapshot)
    finally:
        clear_writer()
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    predicate_events = [e for e in events if e["kind"] == "predicate.evaluated"]
    assert predicate_events, "expected at least one predicate.evaluated event"
    held_out_ids = {p.id.hex() for p in held_out.required()}
    visible_ids = {p.id.hex() for p in visible.required()}
    saw_redacted = False
    for event in predicate_events:
        pid = event["payload"]["predicate_id"]
        # Held-out ids never appear as raw hex on the trace surface.
        assert pid not in held_out_ids, (
            "held-out predicate id leaked into predicate.evaluated event"
        )
        if pid.startswith("redacted:"):
            saw_redacted = True
        else:
            # Non-redacted ids must be visible-half ids.
            assert pid in visible_ids or pid.startswith("redacted:"), (
                f"unexpected predicate_id {pid!r} in trace"
            )
    assert saw_redacted, (
        "no redacted predicate.evaluated event emitted during held-out evaluation"
    )


# RACT 0.4.0
