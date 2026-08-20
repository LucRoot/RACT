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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

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


@dataclass(frozen=True)
class GateOutcome:
    """Result of running a pre-commit gate on a step transaction."""

    passed: bool
    should_roll_back: bool
    report: MutationReport


@dataclass(frozen=True)
class PatchDiffGateOutcome:
    """Result of running G3 on a step transaction."""

    passed: bool
    should_roll_back: bool
    report: PatchDifferentiationReport


@dataclass(frozen=True)
class CoverageDeltaGateOutcome:
    """Result of running G4 on a step transaction."""

    passed: bool
    should_roll_back: bool
    report: CoverageDeltaReport


@dataclass(frozen=True)
class TestIntegrityGateOutcome:
    """Result of running G5 on a step transaction.

    The class name starts with ``Test`` because it wraps
    ``TestIntegrityReport``; the ``__test__ = False`` guard tells
    pytest not to try to collect it as a test case.
    """

    __test__ = False

    passed: bool
    should_roll_back: bool
    report: TestIntegrityReport


@dataclass(frozen=True)
class UnderEditGateOutcome:
    """Result of running G6 on a step transaction."""

    passed: bool
    should_roll_back: bool
    report: UnderEditReport


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
        return GateOutcome(passed=True, should_roll_back=False, report=report)
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
    return GateOutcome(passed=False, should_roll_back=True, report=report)


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
        return PatchDiffGateOutcome(passed=True, should_roll_back=False, report=report)
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
    return PatchDiffGateOutcome(passed=False, should_roll_back=True, report=report)


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
            passed=True, should_roll_back=False, report=report
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
    return CoverageDeltaGateOutcome(passed=False, should_roll_back=True, report=report)


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
            passed=True, should_roll_back=False, report=report
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
    return TestIntegrityGateOutcome(passed=False, should_roll_back=True, report=report)


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
        return UnderEditGateOutcome(passed=True, should_roll_back=False, report=report)
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
    return UnderEditGateOutcome(passed=False, should_roll_back=True, report=report)


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
    """Result of running the polyglot dead-code gate on a file set."""

    passed: bool
    should_roll_back: bool
    # ``report`` typed as ``object`` to avoid a hard import cycle
    # between ``ract.antilazy.pre_commit`` and the polyglot module at
    # type-check time; the runtime shape is
    # :class:`~ract.antilazy.dead_code_polyglot.DeadCodePolyglotReport`.
    report: object


@dataclass(frozen=True)
class TestCopyPastePolyglotGateOutcome:
    """Result of running the polyglot copy-paste gate on a file set.

    ``__test__ = False`` keeps pytest from trying to collect this
    dataclass on account of the ``Test`` prefix.
    """

    __test__ = False

    passed: bool
    should_roll_back: bool
    # See :class:`DeadCodePolyglotGateOutcome`.
    report: object


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
            passed=True, should_roll_back=False, report=report
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
        passed=False, should_roll_back=True, report=report
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
            passed=True, should_roll_back=False, report=report
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
        passed=False, should_roll_back=True, report=report
    )


# RACT 0.4.0
