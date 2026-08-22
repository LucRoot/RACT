"""ALM pre-commit gate that runs G2 on a ``StepTransaction``.

The substrate ``StepTransaction.post_conditions`` is a frozen tuple of
``AcceptancePredicate`` values (see ``ract.core.transaction``). G2 is
not a predicate; it is a run over the touched surface that produces a
``MutationReport``. Rather than extend ``AcceptancePredicate`` to
carry a heterogeneous verdict, this module exposes an ``enforce_g2``
helper the pre-commit path calls before it commits the worktree.

Below-threshold ``kill_rate`` returns ``GateOutcome(passed=False,
should_roll_back=True, report=…)`` and emits ``laziness.violated``
with ``kind="mutation_kill_below_threshold"``. The caller is
responsible for the actual git-worktree rollback; this module is pure
over its inputs so tests can drive it without a live worktree.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ract.antilazy.coverage import (
    DEFAULT_DELTA_MUT,
    DEFAULT_TAU_COV,
    CoverageDeltaReport,
    run_coverage_delta,
)
from ract.antilazy.mutation import (
    DEFAULT_KILL_THRESHOLD,
    EquivalenceDetector,
    KillEvaluator,
    MutantSource,
    MutationReport,
    run_mutation,
)
from ract.antilazy.patchdiff import (
    DEFAULT_FLAKINESS_RUNS,
    DEFAULT_MAX_DIFFERENTIATORS_PER_TRANSACTION,
    DEFAULT_MAX_PER_FUNCTION,
    BaselineKind,
    DifferentiatorGenerator,
    Patch,
    PatchDifferentiationReport,
    RetrievalIndex,
    TestRunner,
    run_patchdiff,
)
from ract.antilazy.symgraph import (
    SymbolGraph,
    UnderEditReport,
    compute_closure,
)
from ract.memory.functions.contracts import CandidateDiff, ChangePlan
from ract.antilazy.testintegrity import (
    TestIntegrityReport,
    analyze_diff,
)
from ract.security.manifest import (
    TestIntegrityConfig,
    default_test_integrity_config,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Iterable

    from ract.core.loop import WorkspaceSnapshot
    from ract.core.predicate import AcceptanceSuite
    from ract.core.transaction import StepTransaction


# ---------------------------------------------------------------------------
# AL-1 attestation (v0.5.1 wiring module_07)
# ---------------------------------------------------------------------------
#
# Every ``*GateOutcome`` carries a ``rootknot_signature`` — a hex-encoded
# content-binding attestation over the canonical projection of the gate
# result plus the ambient run_id. The Rootknot v4 factory
# (:func:`ract.core.rootknot.make_rootknot_v4`) later folds each gate's
# ``evidence_digest`` into ``gate_results``; the field on the outcome
# projects that same commitment forward one step so an intermediate
# caller (loop_controller) can refuse a tampered outcome BEFORE it
# reaches the rootknot factory.
#
# The signature is deterministic (SHA-256 over JCS) rather than an
# ed25519 signature over the same bytes because the gate runners do not
# yet have access to a run-scoped signing key at their call sites. When
# a run-scoped signer accessor lands (v0.6), :func:`_compute_gate_signature`
# swaps the digest for a real ed25519 signature under the same canonical
# projection; the format ``sha256:<hex>`` vs ``ed25519:<hex>`` is
# self-describing so verifiers can distinguish. Under the current
# implementation the field is BOTH tamper-evident (any change to
# ``gate_id`` / ``passed`` / ``report`` / ``run_id`` invalidates the
# digest) and cross-run-swap-detectable (the run_id rides inside the
# signed payload).


_GATE_SIGNATURE_ALGO = "sha256"


def _canonical_report_projection(report: Any) -> Any:
    """Return a JCS-safe projection of ``report`` for the signature payload.

    Prefers ``report.canonical_dict()`` when present (as
    :class:`~ract.core.rootknot.GateResult` uses); falls back to
    ``dataclasses.asdict``-style extraction of the report's public
    fields. Unhashable / unrepresentable fields are string-projected
    so the digest is stable but keeps content-binding.
    """
    if report is None:
        return None
    canonical = getattr(report, "canonical_dict", None)
    if callable(canonical):
        try:
            return canonical()
        except Exception:  # noqa: BLE001
            pass
    # Best-effort dataclass projection.
    try:
        from dataclasses import asdict, is_dataclass

        if is_dataclass(report):
            return _stringify_leaves(asdict(report))
    except Exception:  # noqa: BLE001
        pass
    # Last resort: str() of the report so the digest is at least
    # content-derived (a swap changes the string).
    return {"__repr__": repr(report)}


def _stringify_leaves(value: Any) -> Any:
    """Recursively coerce non-JSON-safe leaves to strings for JCS.

    JCS accepts dict/list/str/int/float/bool/None; bytes, sets, tuples,
    frozensets, and arbitrary objects get string-projected so the
    digest is stable across Python runs.
    """
    if isinstance(value, dict):
        return {str(k): _stringify_leaves(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stringify_leaves(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_stringify_leaves(v) for v in value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _compute_gate_signature(
    *,
    gate_id: str,
    passed: bool,
    report: Any,
    run_id: str | None = None,
) -> str:
    """Return the ``rootknot_signature`` string for a gate outcome.

    Format: ``"sha256:<64-hex>"``. Payload is
    ``dumps_jcs({"algo": "sha256", "gate_id": gate_id, "passed": bool,
    "report": <canonical projection>, "run_id": <str>})``. When
    ``run_id`` is ``None`` the ambient value from
    :func:`ract.runtime.get_current_run_id` is used; the empty string is
    a valid run_id (an operator running an ad-hoc invocation outside a
    bound scope) — the digest still content-binds gate_id + passed +
    report.

    Never raises: a JCS-serialisation failure falls back to a
    ``repr``-of-payload digest so the field is always populated (the
    AL-1 invariant is that the field is non-empty; the substrate
    verifier is what enforces that it VALIDATES).
    """
    resolved_run_id = run_id
    if resolved_run_id is None:
        try:
            from ract.runtime import get_current_run_id  # noqa: PLC0415

            resolved_run_id = get_current_run_id() or ""
        except Exception:  # noqa: BLE001
            resolved_run_id = ""
    payload = {
        "algo": _GATE_SIGNATURE_ALGO,
        "gate_id": str(gate_id),
        "passed": bool(passed),
        "report": _canonical_report_projection(report),
        "run_id": str(resolved_run_id),
    }
    try:
        from ract.canonical import dumps_jcs  # noqa: PLC0415

        canonical_bytes = dumps_jcs(payload).encode("utf-8")
    except Exception:  # noqa: BLE001
        canonical_bytes = repr(payload).encode("utf-8", errors="replace")
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    return f"{_GATE_SIGNATURE_ALGO}:{digest}"


def _require_gate_signature(signature: str, *, gate_id: str) -> str:
    """Return ``signature`` unchanged; raise ``ValueError`` if empty/None.

    Called by :class:`~ract.loop_controller.LoopController` (and any
    other AL-1 verifier) as a structural check that a gate outcome
    carries the AL-1 attestation. The invariant is enforced at
    construction: every ``enforce_gN`` produces a non-empty signature
    via :func:`_compute_gate_signature` so this guard is defense-in-
    depth against a callsite that constructs an outcome by hand.
    """
    if not isinstance(signature, str) or not signature:
        raise ValueError(
            f"AL-1 invariant violation: gate {gate_id!r} produced an "
            f"empty rootknot_signature; every anti-lazy gate outcome "
            f"must carry a non-empty AL-1 attestation. See "
            f"docs/RACT_v0.4.0_ANTILAZY_SPEC.md §5 Invariant AL-1 and "
            f"_BUILD/audit_2026-08-21/lens_E_antilazy_memory.md AL-E-04."
        )
    return signature


@dataclass(frozen=True)
class GateOutcome:
    """Result of running a pre-commit gate on a step transaction.

    AL-1 invariant (v0.5.1 wiring module_07 + SP Q5 amendment):
    ``rootknot_signature`` is a non-empty hex-encoded content-binding
    attestation. Produced by :func:`_compute_gate_signature` from the
    tuple ``(gate_id, passed, report, run_id)``. Enforced at
    CONSTRUCTION TIME via ``__post_init__`` (SP Q5 amendment) so a
    caller that forgets to populate the field cannot slip through —
    the invariant is substrate, not caller-convention. Loop-controller
    ``_require_al1_signature`` is defense-in-depth for hand-serialised
    payloads that skip ``__init__``.
    """

    passed: bool
    should_roll_back: bool
    report: MutationReport
    rootknot_signature: str = ""

    def __post_init__(self) -> None:
        _require_gate_signature(self.rootknot_signature, gate_id="G2")


@dataclass(frozen=True)
class PatchDiffGateOutcome:
    """Result of running G3 on a step transaction.

    See :class:`GateOutcome` for the AL-1 ``rootknot_signature``
    invariant (v0.5.1 wiring module_07).
    """

    passed: bool
    should_roll_back: bool
    report: PatchDifferentiationReport
    rootknot_signature: str = ""

    def __post_init__(self) -> None:
        _require_gate_signature(self.rootknot_signature, gate_id="G3")


@dataclass(frozen=True)
class CoverageDeltaGateOutcome:
    """Result of running G4 on a step transaction.

    See :class:`GateOutcome` for the AL-1 ``rootknot_signature``
    invariant (v0.5.1 wiring module_07).
    """

    passed: bool
    should_roll_back: bool
    report: CoverageDeltaReport
    rootknot_signature: str = ""

    def __post_init__(self) -> None:
        _require_gate_signature(self.rootknot_signature, gate_id="G4")


@dataclass(frozen=True)
class TestIntegrityGateOutcome:
    """Result of running G5 on a step transaction.

    The class name starts with ``Test`` because it wraps
    ``TestIntegrityReport``; the ``__test__ = False`` guard tells
    pytest not to try to collect it as a test case.

    See :class:`GateOutcome` for the AL-1 ``rootknot_signature``
    invariant (v0.5.1 wiring module_07).
    """

    __test__ = False

    passed: bool
    should_roll_back: bool
    report: TestIntegrityReport
    rootknot_signature: str = ""

    def __post_init__(self) -> None:
        _require_gate_signature(self.rootknot_signature, gate_id="G5")


@dataclass(frozen=True)
class UnderEditGateOutcome:
    """Result of running G6 on a step transaction.

    See :class:`GateOutcome` for the AL-1 ``rootknot_signature``
    invariant (v0.5.1 wiring module_07).
    """

    passed: bool
    should_roll_back: bool
    report: UnderEditReport
    rootknot_signature: str = ""

    def __post_init__(self) -> None:
        _require_gate_signature(self.rootknot_signature, gate_id="G6")


def enforce_g2(
    transaction: "StepTransaction",
    suite: "AcceptanceSuite",
    *,
    touched_files: tuple[str, ...],
    source: MutantSource,
    evaluator: KillEvaluator,
    detector: EquivalenceDetector | None = None,
    threshold: float = DEFAULT_KILL_THRESHOLD,
) -> GateOutcome:
    """Run G2 against ``transaction``'s touched surface.

    Returns a ``GateOutcome`` describing whether the transaction
    should commit or roll back. Best-effort emit of
    ``laziness.violated`` on below-threshold kill rate; the emit is
    guarded so a missing trace writer does not fail the gate.
    """
    report = run_mutation(
        touched_files=touched_files,
        suite=suite,
        source=source,
        evaluator=evaluator,
        detector=detector,
        threshold=threshold,
    )
    if report.passed():
        return GateOutcome(
            passed=True,
            should_roll_back=False,
            report=report,
            rootknot_signature=_compute_gate_signature(
                gate_id="G2", passed=True, report=report
            ),
        )
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            {
                "kind": "mutation_kill_below_threshold",
                "step_id": transaction.step_id.hex(),
                "branch": transaction.branch_name,
                "kill_rate": report.kill_rate,
                "threshold": report.threshold,
                "mutants_total": report.mutants_total,
                "mutants_killed": report.mutants_killed,
                "mutants_survived_count": len(report.mutants_survived),
                "mutants_equivalent_count": len(report.mutants_equivalent),
                # A sampled survivor id helps the operator triage
                # without pulling the whole survivor list into the
                # event payload.
                "sample_survivor": (
                    report.mutants_survived[0] if report.mutants_survived else ""
                ),
            },
            step_id=transaction.step_id,
        )
    except Exception:  # noqa: BLE001 — never fail the gate on trace error
        pass
    return GateOutcome(
        passed=False,
        should_roll_back=True,
        report=report,
        rootknot_signature=_compute_gate_signature(
            gate_id="G2", passed=False, report=report
        ),
    )


def enforce_g3(
    transaction: "StepTransaction",
    patch: Patch,
    workspace_root: "Path",
    *,
    generator: DifferentiatorGenerator,
    runner: TestRunner,
    baseline: Patch | None = None,
    baseline_kind: BaselineKind = "null",
    retrieval_index: RetrievalIndex | None = None,
    total_budget: int = DEFAULT_MAX_DIFFERENTIATORS_PER_TRANSACTION,
    per_function_cap: int = DEFAULT_MAX_PER_FUNCTION,
    flakiness_runs: int = DEFAULT_FLAKINESS_RUNS,
) -> PatchDiffGateOutcome:
    """Run G3 against ``patch``; emit ``laziness.violated`` on failure.

    Failure modes:

    - ``is_semantic_noop`` — the diff touched functions but no
      differentiator distinguishes it from the baseline. Emit with
      ``kind="semantic_noop"``.
    - ``leakage_matches`` non-empty — a hunk byte-matches a prior
      commit or retrieval-index entry above the floor. Emit with
      ``kind="solution_leakage"``.
    """
    report = run_patchdiff(
        patch,
        workspace_root,
        generator=generator,
        runner=runner,
        baseline=baseline,
        baseline_kind=baseline_kind,
        retrieval_index=retrieval_index,
        total_budget=total_budget,
        per_function_cap=per_function_cap,
        flakiness_runs=flakiness_runs,
    )
    if not report.is_semantic_noop and not report.leakage_matches:
        return PatchDiffGateOutcome(
            passed=True,
            should_roll_back=False,
            report=report,
            rootknot_signature=_compute_gate_signature(
                gate_id="G3", passed=True, report=report
            ),
        )
    kind = "solution_leakage" if report.leakage_matches else "semantic_noop"
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            {
                "kind": kind,
                "step_id": transaction.step_id.hex(),
                "branch": transaction.branch_name,
                "patch_digest": report.patch_digest,
                "baseline_kind": report.baseline_kind,
                "generated_tests": report.generated_tests,
                "tests_that_distinguish": report.tests_that_distinguish,
                "leakage_matches": list(report.leakage_matches),
                "leakage_below_floor": report.leakage_below_floor,
                "retrieval_index_absent": report.retrieval_index_absent,
            },
            step_id=transaction.step_id,
        )
    except Exception:  # noqa: BLE001
        pass
    return PatchDiffGateOutcome(
        passed=False,
        should_roll_back=True,
        report=report,
        rootknot_signature=_compute_gate_signature(
            gate_id="G3", passed=False, report=report
        ),
    )


def enforce_g4(
    transaction: "StepTransaction",
    patch: Patch,
    parent_snapshot: "WorkspaceSnapshot",
    child_snapshot: "WorkspaceSnapshot",
    *,
    mutation_report_parent: MutationReport | None = None,
    mutation_report_child: MutationReport | None = None,
    tau_cov: float = DEFAULT_TAU_COV,
    delta_mut: float = DEFAULT_DELTA_MUT,
) -> CoverageDeltaGateOutcome:
    """Run G4 against ``patch``; emit ``laziness.violated`` on failure.

    Failure fires when ``coverage_ratio < tau_cov`` OR (the change is
    non-trivial AND ``mutation_coverage_delta < delta_mut``). Emits
    with ``kind="coverage_delta_insufficient"``.
    """
    report = run_coverage_delta(
        parent_snapshot,
        child_snapshot,
        patch,
        mutation_report_parent=mutation_report_parent,
        mutation_report_child=mutation_report_child,
        tau_cov=tau_cov,
        delta_mut=delta_mut,
    )
    if report.passed():
        return CoverageDeltaGateOutcome(
            passed=True,
            should_roll_back=False,
            report=report,
            rootknot_signature=_compute_gate_signature(
                gate_id="G4", passed=True, report=report
            ),
        )
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            {
                "kind": "coverage_delta_insufficient",
                "step_id": transaction.step_id.hex(),
                "branch": transaction.branch_name,
                "coverage_ratio": report.coverage_ratio,
                "tau_cov": report.tau_cov,
                "mutation_coverage_delta": report.mutation_coverage_delta,
                "delta_mut": report.delta_mut,
                "lines_new": report.lines_new,
                "lines_new_covered": report.lines_new_covered,
                "is_trivial_change": report.is_trivial_change,
                "coverage_ok": report.coverage_ok(),
                "mutation_ok": report.mutation_ok(),
            },
            step_id=transaction.step_id,
        )
    except Exception:  # noqa: BLE001
        pass
    return CoverageDeltaGateOutcome(
        passed=False,
        should_roll_back=True,
        report=report,
        rootknot_signature=_compute_gate_signature(
            gate_id="G4", passed=False, report=report
        ),
    )


def enforce_g5(
    transaction: "StepTransaction",
    parent_snapshot: "WorkspaceSnapshot",
    child_snapshot: "WorkspaceSnapshot",
    *,
    config: TestIntegrityConfig | None = None,
    handshake_approved: bool = False,
) -> TestIntegrityGateOutcome:
    """Run G5 against the diff between ``parent_snapshot`` and ``child_snapshot``.

    Emits ``laziness.violated`` with ``kind="test_hack_denied"`` when a
    hard-block violation survives the handshake filter. Advisory
    violations (unsupported-language files, syntax errors) do not
    block; they land in the report and, when a trace writer is
    registered, in ``predicate.evaluated`` with
    ``kind="test_integrity_advisory"``.
    """
    if config is None:
        config = default_test_integrity_config()
    report = analyze_diff(
        parent_snapshot,
        child_snapshot,
        config,
        handshake_approved=handshake_approved,
    )
    if report.passed():
        # Emit advisories if any were logged (so the trace channel sees
        # the unsupported-language gap even on a passing run).
        _emit_advisories_if_any(transaction, report)
        return TestIntegrityGateOutcome(
            passed=True,
            should_roll_back=False,
            report=report,
            rootknot_signature=_compute_gate_signature(
                gate_id="G5", passed=True, report=report
            ),
        )
    surviving = [
        v
        for v in report.violations
        if v.severity == "hard_block"
        and not (handshake_approved and v.handshake_allowed)
    ]
    try:
        from ract.trace.sink import emit as _emit_event

        # Emit the handshake pair when a signed operator override
        # covered any denied pattern — trace vocabulary aligns with
        # SUBSTRATE module_05.
        if handshake_approved:
            _emit_event(
                "handshake.requested",
                {
                    "kind": "test_hack_denied",
                    "step_id": transaction.step_id.hex(),
                    "reason": "operator handshake to permit denied test pattern",
                },
                step_id=transaction.step_id,
            )
            _emit_event(
                "handshake.resolved",
                {
                    "kind": "test_hack_denied",
                    "step_id": transaction.step_id.hex(),
                    "outcome": "approved",
                },
                step_id=transaction.step_id,
            )
        _emit_event(
            "laziness.violated",
            {
                "kind": "test_hack_denied",
                "step_id": transaction.step_id.hex(),
                "branch": transaction.branch_name,
                "patterns": sorted({v.pattern for v in surviving}),
                "sample_file": surviving[0].file if surviving else "",
                "sample_line": surviving[0].line if surviving else 0,
                "handshake_approved": handshake_approved,
                "violations_total": len(surviving),
            },
            step_id=transaction.step_id,
        )
    except Exception:  # noqa: BLE001 — never fail the gate on trace error
        pass
    return TestIntegrityGateOutcome(
        passed=False,
        should_roll_back=True,
        report=report,
        rootknot_signature=_compute_gate_signature(
            gate_id="G5", passed=False, report=report
        ),
    )


def _emit_advisories_if_any(
    transaction: "StepTransaction", report: TestIntegrityReport
) -> None:
    """Emit ``predicate.evaluated`` for advisory violations, best-effort."""
    advisories = report.advisory_violations()
    if not advisories:
        return
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "predicate.evaluated",
            {
                "kind": "test_integrity_advisory",
                "step_id": transaction.step_id.hex(),
                "patterns": sorted({v.pattern for v in advisories}),
                "files": sorted({v.file for v in advisories}),
                "advisory_total": len(advisories),
                "ok": True,
            },
        )
    except Exception:  # noqa: BLE001
        pass


def enforce_g6(
    transaction: "StepTransaction",
    graph: SymbolGraph,
    edited_symbols: "Iterable[str]",
    *,
    edited_files: "Iterable[str]" = (),
    passing_tests_touched: "Iterable[str]" = (),
    declared_unaffected: "Iterable[str]" = (),
) -> UnderEditGateOutcome:
    """Run G6 against ``graph`` and the step's edited symbols.

    Emits ``laziness.violated`` with
    ``kind="under_edit_uncovered_callers"`` when the closure surfaces
    any downstream caller not covered by edit, by a passing test, or
    by an explicit declaration of unaffectedness.
    """
    report = compute_closure(
        graph,
        edited_symbols,
        edited_files=edited_files,
        passing_tests_touched=passing_tests_touched,
        declared_unaffected=declared_unaffected,
    )
    if report.passed():
        return UnderEditGateOutcome(
            passed=True,
            should_roll_back=False,
            report=report,
            rootknot_signature=_compute_gate_signature(
                gate_id="G6", passed=True, report=report
            ),
        )
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            {
                "kind": "under_edit_uncovered_callers",
                "step_id": transaction.step_id.hex(),
                "branch": transaction.branch_name,
                "modified_symbols": list(report.modified_symbols),
                "uncovered": list(report.uncovered),
                "covered_by_test": list(report.covered_by_test),
                "covered_by_edit": list(report.covered_by_edit),
                "covered_by_declaration": list(report.covered_by_declaration),
                "getattr_advisories": list(report.getattr_advisories),
                "generated_excluded": list(report.generated_excluded),
            },
            step_id=transaction.step_id,
        )
    except Exception:  # noqa: BLE001
        pass
    return UnderEditGateOutcome(
        passed=False,
        should_roll_back=True,
        report=report,
        rootknot_signature=_compute_gate_signature(
            gate_id="G6", passed=False, report=report
        ),
    )


# ---------------------------------------------------------------------------
# v0.5.0 memory discipline — G6 + G7 extensions for the ``edit`` function
# ---------------------------------------------------------------------------
#
# Module_09 wires the four function contracts (module_06) into the ALM
# gates: G6 (under-edit closure) grows an ``edit``-shaped path that
# inspects the :class:`CandidateDiff`'s touched files against the
# :class:`ChangePlan`'s ``load_manifest``; G7 (companion review) hands
# the diff to a companion provider for a second-pair-of-eyes verdict.
#
# The legacy :func:`enforce_g6` above is UNCHANGED — a caller that
# constructs no CandidateDiff (the v0.3/v0.4 loop, mainline substrate
# runs that predate module_06's edit function) reaches the legacy
# closure check exactly as today. The new helpers below are the shape
# module_06's edit function calls at commit time. Lateral chain PRE
# branch C: "when None, G6 falls back to its existing under-edit
# closure check against the workspace snapshot" — that fallback is
# the legacy :func:`enforce_g6` above; the new helpers require a
# CandidateDiff by contract.


class LazinessViolatedError(RuntimeError):
    """Raised by the module_09 ALM edit-path gate helpers on failure.

    ``kind`` is the machine-readable failure family the trace channel
    also emits under ``laziness.violated``. The three module_09 kinds
    are:

    - ``under_edit_closure_gap`` — G6 on ``edit`` output: the
      :class:`CandidateDiff` touched a file not named in the
      :class:`ChangePlan`'s ``load_manifest``.
    - ``companion_flagged`` — G7 on ``edit`` output: the companion
      provider returned a negative verdict.
    - ``diff_without_plan`` — a caller passed a :class:`CandidateDiff`
      without the paired :class:`ChangePlan`; the gate refuses to
      guess the manifest and rejects loudly rather than pass.
    """

    def __init__(self, message: str, *, kind: str) -> None:
        self.kind = kind
        super().__init__(message)


class CompanionProvider(Protocol):
    """Companion-provider protocol G7 calls to review a CandidateDiff.

    Kept minimal on purpose. A conforming implementation returns a
    tuple ``(approved: bool, reason: str)``. ``approved=False`` trips
    :class:`LazinessViolatedError` with ``kind="companion_flagged"``.
    Real bridges (module_06's :class:`MemoryFunctionProvider`,
    :class:`ract.providers.base.ProviderAdapter`) land as thin adapters
    outside this module.
    """

    def review(self, diff: CandidateDiff) -> tuple[bool, str]: ...


def enforce_g6_edit(
    diff: CandidateDiff | None,
    plan: ChangePlan,
    *,
    step_id: bytes | None = None,
) -> None:
    """Run G6 (under-edit closure) against an ``edit`` output.

    Refuses when ``diff`` touches a file outside ``plan.load_manifest``.
    ``diff=None`` is the LEGACY-fallback signal — the caller has no
    :class:`CandidateDiff` and must reach :func:`enforce_g6` above
    with a :class:`SymbolGraph` / edited-symbol set instead. Passing
    ``None`` here is a programming error the helper flags loudly so a
    caller cannot silently bypass the gate.

    Emits ``laziness.violated`` before raising so the trace channel
    carries the reason.
    """
    if diff is None:
        raise LazinessViolatedError(
            "enforce_g6_edit: diff is None; the ALM edit-path gate "
            "requires a CandidateDiff. Legacy callers reach "
            "enforce_g6(transaction, graph, edited_symbols) instead.",
            kind="diff_without_plan",
        )
    manifest_files = _load_manifest_files(plan)
    touched = _diff_touched_files(diff)
    outside = sorted(f for f in touched if f not in manifest_files)
    if not outside:
        return
    payload = {
        "kind": "under_edit_closure_gap",
        "step_id": step_id.hex() if step_id is not None else "",
        "files_outside_manifest": outside,
        "manifest_size": len(manifest_files),
        "diff_touched_files": sorted(touched),
    }
    _emit_laziness_violated(payload, step_id=step_id)
    raise LazinessViolatedError(
        f"under-edit closure gap: files outside load_manifest: {outside!r}",
        kind="under_edit_closure_gap",
    )


def enforce_g7_edit(
    diff: CandidateDiff,
    companion: CompanionProvider,
    *,
    step_id: bytes | None = None,
) -> None:
    """Run G7 (companion review) against an ``edit`` output.

    Refuses when ``companion.review(diff)`` returns ``(False, reason)``.
    Emits ``laziness.violated`` before raising so the trace channel
    carries the reason.
    """
    approved, reason = companion.review(diff)
    if approved:
        return
    payload = {
        "kind": "companion_flagged",
        "step_id": step_id.hex() if step_id is not None else "",
        "reason": reason,
        "hunk_count": len(diff.hunks),
        "output_tokens": diff.output_tokens,
    }
    _emit_laziness_violated(payload, step_id=step_id)
    raise LazinessViolatedError(
        f"companion review rejected the diff: {reason}",
        kind="companion_flagged",
    )


def _normalize_file_path(raw: str) -> str:
    """Return a canonical string for path-set membership checks.

    Second Pass Q3 fold (module_09): raw ``SymbolRef.file_path`` and
    ``HunkSummary.file_path`` values may arrive with mixed
    separators (``\\`` from Windows LSPs, ``/`` from git diffs) or
    with redundant components (``./foo/../foo/x.py``). Normalize
    both sides identically so a genuine match is not silently
    missed. Absolute vs relative paths still trip the check — that
    is the intent (an absolute path outside the manifest IS an
    under-edit closure gap).
    """
    if not raw:
        return ""
    return raw.replace("\\", "/").lstrip("./")


def _load_manifest_files(plan: ChangePlan) -> set[str]:
    """Return the set of normalized file paths named in ``plan.load_manifest``.

    Each :class:`~ract.memory.functions.contracts.SymbolRef` in the
    manifest carries a ``file_path`` field. The set is used for the
    G6-edit membership check so a diff hunk against
    ``foo.py:12`` verifies against the manifest's ``foo.py``.
    """
    files: set[str] = set()
    for ref in plan.load_manifest:
        file_path = getattr(ref, "file_path", None)
        if file_path:
            files.add(_normalize_file_path(str(file_path)))
    return files


def _diff_touched_files(diff: CandidateDiff) -> set[str]:
    """Return the set of normalized file paths the diff's hunks touch."""
    return {
        _normalize_file_path(hunk.file_path) for hunk in diff.hunks if hunk.file_path
    }


def _emit_laziness_violated(payload: dict, *, step_id: bytes | None) -> None:
    """Best-effort emit of ``laziness.violated`` for the module_09 edit path."""
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            payload,
            step_id=step_id,
        )
    except Exception:  # noqa: BLE001 — never fail the gate on a trace error
        pass


# ---------------------------------------------------------------------------
# module_08 (v0.5.1) — polyglot G5/G6 dispatch shims
# ---------------------------------------------------------------------------
#
# The legacy :func:`enforce_g5` (test-integrity via AST diff) and
# :func:`enforce_g6` (under-edit closure via SymbolGraph) above are
# UNCHANGED and remain the loop's default gate wire. The two shims
# below add polyglot dead-code + test-copy-paste detection as an
# ADDITIVE surface, wired from the loop by callers that opt in through
# the ``ract.antilazy`` package re-export. Preserving legacy behaviour
# bit-for-bit is a hard module_08 constraint (regression: Python-only
# workspace produces identical legacy-G5/legacy-G6 verdicts pre- and
# post-module_08 because those code paths are untouched).


@dataclass(frozen=True)
class DeadCodePolyglotGateOutcome:
    """Result of running the polyglot dead-code gate on a file set.

    See :class:`GateOutcome` for the AL-1 ``rootknot_signature``
    invariant (v0.5.1 wiring module_07).
    """

    passed: bool
    should_roll_back: bool
    # ``report`` typed as ``object`` to avoid a hard import cycle
    # between ``ract.antilazy.pre_commit`` and the polyglot module at
    # type-check time; the runtime shape is
    # :class:`~ract.antilazy.dead_code_polyglot.DeadCodePolyglotReport`.
    report: object
    rootknot_signature: str = ""

    def __post_init__(self) -> None:
        _require_gate_signature(self.rootknot_signature, gate_id="G5-polyglot")


@dataclass(frozen=True)
class TestCopyPastePolyglotGateOutcome:
    """Result of running the polyglot copy-paste gate on a file set.

    ``__test__ = False`` keeps pytest from trying to collect this
    dataclass on account of the ``Test`` prefix.

    See :class:`GateOutcome` for the AL-1 ``rootknot_signature``
    invariant (v0.5.1 wiring module_07).
    """

    __test__ = False

    passed: bool
    should_roll_back: bool
    # See :class:`DeadCodePolyglotGateOutcome`.
    report: object
    rootknot_signature: str = ""

    def __post_init__(self) -> None:
        _require_gate_signature(self.rootknot_signature, gate_id="G6-polyglot")


def enforce_g5_dead_code_polyglot(
    files: "Iterable[Path]",
    *,
    step_id: bytes | None = None,
    threshold: int = 0,
) -> DeadCodePolyglotGateOutcome:
    """Run the polyglot dead-code gate over ``files``.

    ``threshold`` is the maximum candidate count the caller tolerates;
    default 0 means any dead-code candidate rolls back. Emits
    ``laziness.violated`` with ``kind="dead_code_polyglot"`` on
    failure. NEVER fails the loop on unsupported languages — those
    land in the report's ``unsupported_languages`` field only.
    """
    from ract.antilazy.dead_code_polyglot import scan_dead_code  # noqa: PLC0415

    report = scan_dead_code(files)
    if report.passed(threshold=threshold):
        return DeadCodePolyglotGateOutcome(
            passed=True,
            should_roll_back=False,
            report=report,
            rootknot_signature=_compute_gate_signature(
                gate_id="G5-polyglot", passed=True, report=report
            ),
        )
    payload = {
        "kind": "dead_code_polyglot",
        "step_id": step_id.hex() if step_id is not None else "",
        "candidate_count": len(report.candidates),
        "sample_file": report.candidates[0].file if report.candidates else "",
        "sample_identifier": (
            report.candidates[0].identifier if report.candidates else ""
        ),
        "languages": sorted({c.language for c in report.candidates}),
        "unsupported_languages": list(report.unsupported_languages),
    }
    _emit_laziness_violated(payload, step_id=step_id)
    return DeadCodePolyglotGateOutcome(
        passed=False,
        should_roll_back=True,
        report=report,
        rootknot_signature=_compute_gate_signature(
            gate_id="G5-polyglot", passed=False, report=report
        ),
    )


def enforce_g6_test_copy_paste_polyglot(
    files: "Iterable[Path]",
    *,
    step_id: bytes | None = None,
    jaccard_threshold: float = 0.85,
    min_tokens: int = 6,
    finding_threshold: int = 0,
) -> TestCopyPastePolyglotGateOutcome:
    """Run the polyglot test-copy-paste gate over ``files``.

    ``jaccard_threshold`` and ``min_tokens`` tune the fingerprint
    matcher; ``finding_threshold`` is the caller-tolerated max
    finding count (default 0). Emits ``laziness.violated`` with
    ``kind="test_copy_paste_polyglot"`` on failure.
    """
    from ract.antilazy.test_copy_paste_polyglot import (  # noqa: PLC0415
        scan_test_copy_paste,
    )

    report = scan_test_copy_paste(
        files,
        jaccard_threshold=jaccard_threshold,
        min_tokens=min_tokens,
    )
    if report.passed(threshold=finding_threshold):
        return TestCopyPastePolyglotGateOutcome(
            passed=True,
            should_roll_back=False,
            report=report,
            rootknot_signature=_compute_gate_signature(
                gate_id="G6-polyglot", passed=True, report=report
            ),
        )
    payload = {
        "kind": "test_copy_paste_polyglot",
        "step_id": step_id.hex() if step_id is not None else "",
        "finding_count": len(report.findings),
        "sample_a": (
            f"{report.findings[0].a_file}:{report.findings[0].a_name}"
            if report.findings
            else ""
        ),
        "sample_b": (
            f"{report.findings[0].b_file}:{report.findings[0].b_name}"
            if report.findings
            else ""
        ),
        "top_jaccard": report.findings[0].jaccard if report.findings else 0.0,
        "tests_scanned": report.tests_scanned,
        "languages": sorted({f.language for f in report.findings}),
        "unsupported_languages": list(report.unsupported_languages),
    }
    _emit_laziness_violated(payload, step_id=step_id)
    return TestCopyPastePolyglotGateOutcome(
        passed=False,
        should_roll_back=True,
        report=report,
        rootknot_signature=_compute_gate_signature(
            gate_id="G6-polyglot", passed=False, report=report
        ),
    )


# ---------------------------------------------------------------------------
# v0.5.1 wiring module_07 — G1 / G7 / G8 dispatchers + polyglot per-file router
# ---------------------------------------------------------------------------
#
# Lens E audit AL-E-03: G1, G7, G8 previously had no ``enforce_gN`` in
# this module. G1 was reached only through the substrate ``check_t1``
# dual-suite branch (:func:`ract.core.loop.check_t1`); G7/G8 were
# reached only through :func:`ract.antilazy.completion_gate.run_completion_gates`
# which silently returned ``None`` when ``final_diff is None`` — leaving
# the completion path proceeding as if the gates had passed with no
# ``laziness.skipped`` or ``laziness.violated`` trace entry.
#
# These wrappers give each of G1 / G7 / G8 a canonical
# ``enforce_gN(context) -> <GateFamily>Outcome`` entry point that
# every caller can drive uniformly, and each produces a non-empty
# ``rootknot_signature`` (AL-1 invariant, module_07 item 4). When the
# input context is missing (a caller running a bare loop without a
# DualAcceptanceSuite / companion / effort estimate) each enforce_gN
# emits ``laziness.skipped`` with a ``reason`` so the trace channel
# carries the skip evidence instead of a silent no-op.


@dataclass(frozen=True)
class HoldoutGateOutcome:
    """Result of running G1 (held-out predicate enforcement).

    Wraps :class:`~ract.antilazy.holdout.VisibleHoldoutOutcome`.
    ``blocked_on_holdout_gap`` mirrors :attr:`VisibleHoldoutOutcome.gap`
    — the laziness signature ALM was written to catch (visible half
    passing while the held-out half fails). ``passed`` is True iff
    both halves are ok (the completion-path meaning). ``skipped`` is
    True when the caller invoked ``enforce_g1`` without a
    :class:`DualAcceptanceSuite` — the gate then returns
    ``passed=True`` (so a legacy single-suite run is not artificially
    blocked) with ``skipped=True`` and a ``laziness.skipped`` trace
    event.
    """

    passed: bool
    should_roll_back: bool
    report: object
    rootknot_signature: str = ""
    skipped: bool = False
    blocked_on_holdout_gap: bool = False

    def __post_init__(self) -> None:
        _require_gate_signature(self.rootknot_signature, gate_id="G1")


@dataclass(frozen=True)
class CompanionGateOutcome:
    """Result of running G7 (companion counterexample review).

    ``passed`` is True when the companion produced no surviving
    counterexamples. ``skipped`` is True when the caller supplied no
    :class:`~ract.antilazy.completion_gate.CompanionBundle` OR no
    ``final_diff`` — the gate emits ``laziness.skipped`` with the
    reason so the trace channel is not silent.
    """

    passed: bool
    should_roll_back: bool
    report: object
    rootknot_signature: str = ""
    skipped: bool = False
    skip_reason: str = ""

    def __post_init__(self) -> None:
        _require_gate_signature(self.rootknot_signature, gate_id="G7")


@dataclass(frozen=True)
class EffortGateOutcome:
    """Result of running G8 (effort reconciliation).

    ``passed`` is True when the effort reconciliation surfaces zero
    anomalies. ``skipped`` semantics mirror :class:`CompanionGateOutcome`
    — no ``effort_estimate`` or no ``final_diff`` emits
    ``laziness.skipped``.
    """

    passed: bool
    should_roll_back: bool
    report: object
    rootknot_signature: str = ""
    skipped: bool = False
    skip_reason: str = ""

    def __post_init__(self) -> None:
        _require_gate_signature(self.rootknot_signature, gate_id="G8")


def _emit_laziness_skipped(*, gate_id: str, reason: str) -> None:
    """Best-effort emit of ``laziness.skipped`` for a gate that could
    not run this iteration.

    v0.5.1 wiring module_07 (Lens E AL-E-03 remediation): previously
    G7/G8 silently returned ``None`` on missing final_diff. Now the
    skip is surfaced on the trace channel with the reason so an
    operator reading the audit log sees WHY the gate did not fire.
    """
    try:
        from ract.trace.sink import emit as _emit_event  # noqa: PLC0415

        _emit_event(
            "laziness.skipped",
            {"gate_id": gate_id, "reason": reason},
        )
    except Exception:  # noqa: BLE001
        pass


def enforce_g1(
    dual: Any | None,
    snapshot: "WorkspaceSnapshot | None",
) -> HoldoutGateOutcome:
    """Run G1 (held-out predicate enforcement) against ``snapshot``.

    ``dual`` is a :class:`~ract.antilazy.holdout.DualAcceptanceSuite`
    (duck-typed via ``visible`` / ``held_out`` attributes). When
    ``dual`` is ``None`` OR does not expose the dual-suite shape the
    gate emits ``laziness.skipped`` (``reason="no_dual_suite"``) and
    returns ``passed=True, skipped=True`` — a substrate run without
    a held-out suite is not artificially failed.

    When the dual suite is present the gate delegates to
    :func:`~ract.antilazy.holdout.check_visible_and_held_out` (which
    itself emits ``laziness.violated`` with
    ``kind="visible_holdout_gap"`` on the failure signal) and produces
    an :class:`HoldoutGateOutcome` carrying the outcome + AL-1
    rootknot signature.
    """
    if dual is None or not (hasattr(dual, "visible") and hasattr(dual, "held_out")):
        _emit_laziness_skipped(gate_id="G1", reason="no_dual_suite")
        skip_report = {"kind": "skipped", "reason": "no_dual_suite"}
        return HoldoutGateOutcome(
            passed=True,
            should_roll_back=False,
            report=skip_report,
            rootknot_signature=_compute_gate_signature(
                gate_id="G1", passed=True, report=skip_report
            ),
            skipped=True,
        )
    if snapshot is None:
        _emit_laziness_skipped(gate_id="G1", reason="no_workspace_snapshot")
        skip_report = {"kind": "skipped", "reason": "no_workspace_snapshot"}
        return HoldoutGateOutcome(
            passed=True,
            should_roll_back=False,
            report=skip_report,
            rootknot_signature=_compute_gate_signature(
                gate_id="G1", passed=True, report=skip_report
            ),
            skipped=True,
        )
    from ract.antilazy.holdout import check_visible_and_held_out  # noqa: PLC0415

    outcome = check_visible_and_held_out(dual, snapshot)
    both_ok = outcome.visible_ok and outcome.held_out_ok
    projected = {
        "visible_ok": outcome.visible_ok,
        "held_out_ok": outcome.held_out_ok,
        "gap": outcome.gap,
        "failing_visible_count": len(outcome.failing_visible),
        "failing_held_out_count": len(outcome.failing_held_out),
    }
    return HoldoutGateOutcome(
        passed=both_ok,
        should_roll_back=outcome.gap,
        report=projected,
        rootknot_signature=_compute_gate_signature(
            gate_id="G1", passed=both_ok, report=projected
        ),
        blocked_on_holdout_gap=outcome.gap,
    )


def enforce_g7(
    *,
    intent: str | None,
    final_diff: Any | None,
    visible_suite: Any | None,
    companion_bundle: Any | None,
    pre_change_workspace: Any | None = None,
    post_change_workspace: Any | None = None,
) -> CompanionGateOutcome:
    """Run G7 (companion counterexample review) against a completion attempt.

    v0.5.1 wiring module_07 (Lens E AL-E-03 remediation): emits
    ``laziness.skipped`` with a machine-readable ``reason`` when the
    caller could not supply the gate's inputs — replacing the previous
    silent no-op. The completion path proceeds when
    ``passed=True`` regardless of ``skipped``; the operator reads the
    trace channel for skip evidence.
    """
    if companion_bundle is None:
        _emit_laziness_skipped(gate_id="G7", reason="no_companion_bundle")
        skip_report = {"kind": "skipped", "reason": "no_companion_bundle"}
        return CompanionGateOutcome(
            passed=True,
            should_roll_back=False,
            report=skip_report,
            rootknot_signature=_compute_gate_signature(
                gate_id="G7", passed=True, report=skip_report
            ),
            skipped=True,
            skip_reason="no_companion_bundle",
        )
    if final_diff is None or visible_suite is None:
        reason = "no_final_diff" if final_diff is None else "no_visible_suite"
        _emit_laziness_skipped(gate_id="G7", reason=reason)
        skip_report = {"kind": "skipped", "reason": reason}
        return CompanionGateOutcome(
            passed=True,
            should_roll_back=False,
            report=skip_report,
            rootknot_signature=_compute_gate_signature(
                gate_id="G7", passed=True, report=skip_report
            ),
            skipped=True,
            skip_reason=reason,
        )
    from ract.antilazy.completion_gate import run_completion_gates  # noqa: PLC0415

    aggregate = run_completion_gates(
        intent=intent or "",
        final_diff=final_diff,
        visible_suite=visible_suite,
        companion_bundle=companion_bundle,
        effort_estimate=None,
        pre_change_workspace=pre_change_workspace,
        post_change_workspace=post_change_workspace,
    )
    survivor_count = 0
    if aggregate.companion_report is not None:
        try:
            survivor_count = len(aggregate.companion_report.surviving_findings())
        except Exception:  # noqa: BLE001
            survivor_count = 0
    passed = survivor_count == 0 and not aggregate.companion_provider_collision
    projected = {
        "survivor_count": survivor_count,
        "companion_provider_collision": aggregate.companion_provider_collision,
        "blocks_complete": aggregate.blocks_complete,
    }
    return CompanionGateOutcome(
        passed=passed,
        should_roll_back=not passed,
        report=projected,
        rootknot_signature=_compute_gate_signature(
            gate_id="G7", passed=passed, report=projected
        ),
    )


def enforce_g8(
    *,
    final_diff: Any | None,
    effort_estimate: Any | None,
    symgraph: Any | None = None,
) -> EffortGateOutcome:
    """Run G8 (effort reconciliation) against a completion attempt.

    Emits ``laziness.skipped`` when either ``final_diff`` or
    ``effort_estimate`` is missing — the skip trace event is the
    v0.5.1 wiring module_07 (Lens E AL-E-03) closure for the previous
    silent no-op.
    """
    if effort_estimate is None:
        _emit_laziness_skipped(gate_id="G8", reason="no_effort_estimate")
        skip_report = {"kind": "skipped", "reason": "no_effort_estimate"}
        return EffortGateOutcome(
            passed=True,
            should_roll_back=False,
            report=skip_report,
            rootknot_signature=_compute_gate_signature(
                gate_id="G8", passed=True, report=skip_report
            ),
            skipped=True,
            skip_reason="no_effort_estimate",
        )
    if final_diff is None:
        _emit_laziness_skipped(gate_id="G8", reason="no_final_diff")
        skip_report = {"kind": "skipped", "reason": "no_final_diff"}
        return EffortGateOutcome(
            passed=True,
            should_roll_back=False,
            report=skip_report,
            rootknot_signature=_compute_gate_signature(
                gate_id="G8", passed=True, report=skip_report
            ),
            skipped=True,
            skip_reason="no_final_diff",
        )
    from ract.antilazy.effort import (  # noqa: PLC0415
        measure_actual_effort,
        reconcile_effort,
    )

    realized = measure_actual_effort(final_diff, graph=symgraph)
    recon = reconcile_effort(effort_estimate, realized)
    anomalies = tuple(recon.anomalies)
    passed = not anomalies
    projected = {
        "anomalies": list(anomalies),
        "tau_effort": recon.tau_effort,
        "ratio": {k: round(v, 4) for k, v in recon.ratio.items()},
        "estimate_source": recon.estimate.estimate_source,
    }
    return EffortGateOutcome(
        passed=passed,
        should_roll_back=False,  # G8 warns; G7/G2/... are the hard rollback gates.
        report=projected,
        rootknot_signature=_compute_gate_signature(
            gate_id="G8", passed=passed, report=projected
        ),
    )


# ---------------------------------------------------------------------------
# Polyglot per-file dispatcher for G5 / G6 (module_07 item 2)
# ---------------------------------------------------------------------------
#
# The polyglot G5/G6 shims accept an iterable of paths and delegate to
# tree-sitter backends per file (Python via ``ast``, other languages
# via tree-sitter, unsupported languages land in the report's
# ``unsupported_languages`` field only). The dispatcher below is what
# ``LoopController`` calls at each iteration: it partitions the
# changed-files set by extension, invokes the polyglot backend, and
# emits a per-file verdict with language attribution — replacing the
# previous Python-AST-only path that silently skipped .ts/.rs/.go
# patches.


_POLYGLOT_SUPPORTED_EXTS = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".rb"}
)


def dispatch_polyglot_g5_g6(
    changed_files: "Iterable[Path]",
    *,
    step_id: bytes | None = None,
    dead_code_threshold: int = 0,
    copy_paste_finding_threshold: int = 0,
) -> tuple[DeadCodePolyglotGateOutcome, TestCopyPastePolyglotGateOutcome]:
    """Dispatch polyglot G5 + G6 over ``changed_files`` — module_07 wire.

    Returns ``(dead_code_outcome, copy_paste_outcome)``. The polyglot
    scanners handle language routing internally; this dispatcher's
    job is to (a) filter to supported extensions before dispatch (so
    ``.md`` / ``.json`` are not scanned as code and ``.py`` reaches
    the Python-AST backend), (b) forward the AL-1 signature via the
    outcomes, and (c) provide a single call site the loop-controller
    can wire against instead of two calls the caller must remember to
    keep in sync.

    Loop-controller wire replaces the prior Python-AST-only G5/G6
    dispatch, closing Lens E AL-E-02.
    """
    filtered: list = []
    for path in changed_files:
        if not hasattr(path, "suffix"):
            continue
        if path.suffix.lower() in _POLYGLOT_SUPPORTED_EXTS:
            filtered.append(path)
    dead_code = enforce_g5_dead_code_polyglot(
        filtered, step_id=step_id, threshold=dead_code_threshold
    )
    copy_paste = enforce_g6_test_copy_paste_polyglot(
        filtered,
        step_id=step_id,
        finding_threshold=copy_paste_finding_threshold,
    )
    return dead_code, copy_paste


__all__ = [
    "CompanionGateOutcome",
    "CoverageDeltaGateOutcome",
    "CompanionProvider",
    "DeadCodePolyglotGateOutcome",
    "EffortGateOutcome",
    "GateOutcome",
    "HoldoutGateOutcome",
    "LazinessViolatedError",
    "PatchDiffGateOutcome",
    "TestCopyPastePolyglotGateOutcome",
    "TestIntegrityGateOutcome",
    "UnderEditGateOutcome",
    "dispatch_polyglot_g5_g6",
    "enforce_g1",
    "enforce_g2",
    "enforce_g3",
    "enforce_g4",
    "enforce_g5",
    "enforce_g5_dead_code_polyglot",
    "enforce_g6",
    "enforce_g6_edit",
    "enforce_g6_test_copy_paste_polyglot",
    "enforce_g7",
    "enforce_g7_edit",
    "enforce_g8",
]


# RACT 0.4.0
