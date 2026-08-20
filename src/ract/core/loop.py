"""Formal recursion loop with T1-T8 termination conditions.

v0.4 change (SUBSTRATE §2 and §11 signals 1-2): T1 (Completion) is now a
fact about the environment. ``LoopState`` carries a frozen
``AcceptanceSuite``; ``check_t1`` returns ``COMPLETE`` only when every
required predicate evaluates ``ok=True`` against the workspace snapshot.
The milestone-oracle path is retained for scheduling/reporting only; no
model opinion terminates the loop.

v0.5.1 module_04 change: T8 (PROMPT_DRIFT) joins T1-T7. The loop
controller recomputes ``compute_prompt_digest(current_intent_text)`` at
the start of every iteration and compares against
``state.suite.prompt_digest``. A mismatch fires T8 -- the loop halts
after emitting a ``run.completed`` event with ``reason:
"T8_PROMPT_DRIFT"`` and forces a rollback to the last known-good
workspace snapshot. Legitimate intent evolution goes through the
operator-signed ``ract intent recompile`` verb which appends a new
suite version to ``.ract/runs/<run_id>/suite_chain.jsonl`` rather than
mutating the existing suite in place.

Rationale in ``docs/ADRs/ADR-0010-acceptance-predicates.md`` and
``docs/ADRs/ADR-T8-prompt-drift.md``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)

from ract.core.assumption_registry import AssumptionRegistry
from ract.core.predicate import AcceptanceSuite
from ract.handshake_registry import HandshakeRegistry
from ract.loop_planner import Milestone
from ract.manager import Plan

if TYPE_CHECKING:
    pass


class TerminationCause(Enum):
    """Why the recursion loop stopped.

    v0.5.1 module_04 SP Q1 (external reviewer PARTIAL verdict, both
    Google and OpenRouter reviewer converged): enum members carry EXPLICIT integer
    values so a serialised value crossing a persistence boundary (e.g.,
    a run report from a v0.5.0 client verifying against a v0.5.1
    report) never shifts silently. New members MUST be appended with a
    fresh integer; the guard test
    ``tests/unit/test_termination_cause_t8.py::test_enum_values_pinned``
    fails any re-numbering.
    """

    COMPLETE = 1  # T1: all required predicates evaluate ok against the snapshot.
    REGRESSED = 2  # T2: quality regressed twice consecutively.
    PROVENANCE_FAILURE = 3  # T3: RK-1 or RK-2 violated.
    ASSUMPTION_BURST = 4  # T4: too many assumptions violated.
    BUDGET_EXHAUSTED = 5  # T5: iteration or wall-time budget exhausted.
    HANDSHAKE_BLOCKED = 6  # T6: unresolved blocking handshake.
    PROVIDER_TIMEOUT = 7  # T7: provider timeout twice consecutively.
    # v0.5.1 module_04: T8 fires when the loop's current intent-text
    # hash diverges from ``state.suite.prompt_digest``. See
    # ``docs/ADRs/ADR-0040-t8-prompt-drift-termination-cause.md``. The
    # loop controller emits a ``run.completed`` event with ``reason:
    # "T8_PROMPT_DRIFT"`` + evidence (expected + actual digest,
    # iteration index) and forces a rollback to the last known-good
    # workspace snapshot before returning.
    PROMPT_DRIFT = 8  # T8: prompt hash diverged from suite.prompt_digest.
    # v0.5.1 module_04 SP Q4b (external reviewer DEFECT verdict, both
    # reviewers agreed): pre-v0.5.1 suites lacking prompt_digest are
    # a control-bypass; a controller with ``strict_prompt_digest=True``
    # (opt-in for v0.5.1, default in v0.6+) fires T9 instead of
    # skipping the check, forcing the operator to run
    # ``ract intent recompile`` to bind a digest before the loop
    # continues.
    PROMPT_DIGEST_MISSING = 9  # T9: strict mode + suite.prompt_digest is None.


@dataclass
class Budget:
    """Bounds on loop execution."""

    max_iterations: int = 10
    wall_time_seconds: float = 300.0
    step_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if self.wall_time_seconds <= 0.0:
            raise ValueError("wall_time_seconds must be > 0")
        if self.step_timeout_seconds <= 0.0:
            raise ValueError("step_timeout_seconds must be > 0")


@dataclass
class WorkspaceSnapshot:
    """Lightweight view of the workspace at a point in time.

    ``metadata`` carries evaluator side-channel results — pytest returncodes,
    mypy exit codes, Hypothesis property outcomes — so gates can be pure over
    ``(invocation, snapshot)`` without spawning subprocesses. See
    ``src/ract/core/gates.py`` for the channel keys.
    """

    files: dict[str, str] = field(default_factory=dict)
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MilestoneReport:
    """Outcome of evaluating one milestone.

    Retained for scheduling and reporting; no longer a T1 input.
    """

    milestone_id: str
    status: str  # "verified" | "pending" | "blocked"
    confidence: float
    verifier_type: str = "unknown"
    justification: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"verified", "pending", "blocked"}:
            raise ValueError(f"Invalid milestone status: {self.status}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence out of range: {self.confidence}")


@dataclass
class QualityScore:
    """Quality observation for one iteration."""

    value: float
    iteration: int
    justification: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"QualityScore value out of range: {self.value}")


@dataclass
class ProviderTimeoutRecord:
    """Track consecutive provider timeouts."""

    step_timed_out: bool = False
    consecutive_timeouts: int = 0


@dataclass
class LoopState:
    """Complete state of the recursion loop.

    The suite is required. A caller that constructs ``LoopState`` without
    one fails at construction — the compile-before-loop rule from SUBSTRATE
    §2 lives here. Lateral chain branch B: a suite with zero required
    predicates is refused with a specific error.
    """

    plan: Plan
    workspace: WorkspaceSnapshot
    suite: AcceptanceSuite
    milestones: list[Milestone] = field(default_factory=list)
    milestone_history: list[MilestoneReport] = field(default_factory=list)
    assumption_registry: AssumptionRegistry = field(default_factory=AssumptionRegistry)
    quality_history: list[QualityScore] = field(default_factory=list)
    iteration: int = 0
    budget: Budget = field(default_factory=Budget)
    handshake_registry: HandshakeRegistry | None = None
    provenance_ok: bool = True
    provider_timeout: ProviderTimeoutRecord = field(
        default_factory=ProviderTimeoutRecord
    )
    start_time: float = 0.0
    # Retained for backwards compatibility with reporting/scheduling
    # heuristics, but no longer read by T1.
    tau_complete: float = 0.95
    delta_regress: float = 0.1
    assumption_burst_threshold: int = 3
    blocking_handshakes: set[str] | None = None
    # v0.5.1 module_04 SP Q4b amendment: opt-in strict mode. When True
    # and ``suite.prompt_digest is None``, T8 fires as PROMPT_DIGEST_MISSING
    # (T9). Default False preserves v0.5.0 compatibility.
    strict_prompt_digest: bool = False
    # v0.5.1 module_04: current iteration's raw operator intent text.
    # Populated by the loop controller BEFORE each iteration runs (see
    # ``ract.loop_controller.LoopController.run``); ``check_t8`` reads
    # it to detect prompt drift against ``suite.prompt_digest``. When
    # ``None`` (pre-v0.5.1 controllers or hermetic property tests that
    # never wire the field), the T8 check is skipped.
    current_intent_text: str | None = None
    # v0.5.1 module_04: last known-good workspace snapshot the controller
    # rolls back to on T8 halt. Recorded before each iteration writes;
    # None until the first iteration's pre-write snapshot exists.
    last_known_good_workspace: WorkspaceSnapshot | None = None

    def __post_init__(self) -> None:
        if self.handshake_registry is None:
            self.handshake_registry = HandshakeRegistry(".")
        if not self.suite.required():
            raise ValueError(
                f"AcceptanceSuite for intent {self.suite.intent_id.hex()} has "
                "zero required predicates; T1 would trivially fire. The "
                "IntentCompiler must produce at least one required predicate "
                "before the loop enters step one."
            )


# Default thresholds retained for the non-T1 predicates.
_DEFAULT_DELTA_REGRESS: float = 0.1
_DEFAULT_ASSUMPTION_BURST: int = 3


def check_t1(
    suite: AcceptanceSuite, snapshot: WorkspaceSnapshot
) -> TerminationCause | None:
    """T1 (Completion): all required predicates evaluate ok against the snapshot.

    The environment decides. ``ProgressOracle`` is not consulted here; its
    score is a scheduling heuristic and reporting axis only.

    ALM module_01: when ``suite`` is a ``DualAcceptanceSuite`` (duck-typed
    via a ``visible`` attribute and a ``held_out`` attribute), the check
    evaluates both halves and fires ``laziness.violated`` with
    ``kind="visible_holdout_gap"`` when the visible half is all-ok but
    the held-out half is not. The substrate return type is preserved:
    a dual suite that passes both halves returns ``COMPLETE`` exactly
    as the substrate suite would.
    """
    # Dual-suite branch: run the ALM check_visible_and_held_out helper,
    # which handles both the gap emit and the auto-pass for
    # holdout_kind="trivial".
    if hasattr(suite, "visible") and hasattr(suite, "held_out"):
        from ract.antilazy.holdout import check_visible_and_held_out

        outcome = check_visible_and_held_out(suite, snapshot)  # type: ignore[arg-type]
        if outcome.visible_ok and outcome.held_out_ok:
            return TerminationCause.COMPLETE
        return None
    required = suite.required()
    if not required:
        return None
    for predicate in required:
        result = predicate.evaluate(snapshot)
        if not result.ok:
            return None
    return TerminationCause.COMPLETE


def check_t2(
    quality_history: list[QualityScore],
    delta_regress: float = _DEFAULT_DELTA_REGRESS,
) -> TerminationCause | None:
    """T2: quality regressed by > delta_regress for two consecutive iterations."""
    if len(quality_history) < 2:
        return None
    last = quality_history[-1]
    previous = quality_history[-2]
    if previous.value - last.value > delta_regress:
        if len(quality_history) >= 3:
            before = quality_history[-3]
            if before.value - previous.value > delta_regress:
                return TerminationCause.REGRESSED
    return None


def check_t3(provenance_ok: bool) -> TerminationCause | None:
    """T3: provenance violation (RK-1 or RK-2 fails)."""
    if not provenance_ok:
        return TerminationCause.PROVENANCE_FAILURE
    return None


def check_t4(
    registry: AssumptionRegistry,
    threshold: int = _DEFAULT_ASSUMPTION_BURST,
) -> TerminationCause | None:
    """T4: more than N assumptions violated in one iteration."""
    if len(registry.violated()) > threshold:
        return TerminationCause.ASSUMPTION_BURST
    return None


def check_t5(
    iteration: int,
    budget: Budget,
    start_time: float,
    now: float,
) -> TerminationCause | None:
    """T5: iteration or wall-time budget exhausted."""
    if iteration >= budget.max_iterations:
        return TerminationCause.BUDGET_EXHAUSTED
    elapsed = now - start_time
    if elapsed >= budget.wall_time_seconds:
        return TerminationCause.BUDGET_EXHAUSTED
    return None


def check_t6(
    registry: HandshakeRegistry,
    blocking_ids: set[str] | None = None,
) -> TerminationCause | None:
    """T6: unresolved handshake blocks the critical path."""
    pending = {item.id for item in registry.pending()}
    if not pending:
        return None
    if blocking_ids is None:
        return TerminationCause.HANDSHAKE_BLOCKED
    if pending & blocking_ids:
        return TerminationCause.HANDSHAKE_BLOCKED
    return None


def check_t7(record: ProviderTimeoutRecord) -> TerminationCause | None:
    """T7: provider timeout exceeds step_timeout twice consecutively."""
    if record.consecutive_timeouts >= 2:
        return TerminationCause.PROVIDER_TIMEOUT
    return None


def check_t8(
    suite: AcceptanceSuite,
    current_intent_text: str,
    *,
    strict: bool = False,
) -> TerminationCause | None:
    """T8 (Prompt Drift): current intent hash diverges from suite.prompt_digest.

    v0.5.1 module_04. Backward-compat: when ``suite.prompt_digest is
    None`` (a pre-v0.5.1 suite) and ``strict`` is False (default), the
    check is skipped (returns ``None``) and the loop controller emits
    a WARN so operators see the missing binding. When present,
    ``compute_prompt_digest(current_intent_text)`` is compared bit-exact;
    on mismatch the loop halts with T8.

    v0.5.1 module_04 SP Q4b (external reviewer DEFECT verdict): when
    ``strict=True`` and ``suite.prompt_digest is None``, the check
    returns ``TerminationCause.PROMPT_DIGEST_MISSING`` (T9) so the loop
    halts and the operator MUST run ``ract intent recompile`` to bind
    a digest before continuing. The default False preserves v0.5.0
    compatibility; v0.6 will flip the default to True.

    The intent-text argument is the CANONICAL operator intent the loop
    entered with (the same bytes ``IntentCompiler.compile`` hashed).
    Callers must pass the raw intent, not the augmented per-iteration
    intent (which carries loop memory + backlog + milestone prefix).
    """
    from ract.core.workspace_digest import compute_prompt_digest

    if suite.prompt_digest is None:
        if strict:
            return TerminationCause.PROMPT_DIGEST_MISSING
        return None
    actual = bytes(compute_prompt_digest(current_intent_text))
    if actual != suite.prompt_digest:
        return TerminationCause.PROMPT_DRIFT
    return None


def evaluate_termination(state: LoopState, now: float) -> TerminationCause | None:
    """Evaluate T1-T8 in order and return the first cause that fires.

    T8 is checked LAST (after the substrate-level T1-T7) so a legitimate
    completion (T1) or a budget/handshake halt (T5/T6) still fires under
    its own cause; T8 only fires when the loop is still live but the
    intent has drifted. A T8 verdict SHOULD be produced by the loop
    controller's per-iteration hook (which also handles the rollback +
    ``run.completed`` emit); ``evaluate_termination`` exposes the check
    here so property tests and reporting paths see the same decision
    surface.
    """
    if cause := check_t1(state.suite, state.workspace):
        return cause
    if cause := check_t2(state.quality_history, state.delta_regress):
        return cause
    if cause := check_t3(state.provenance_ok):
        return cause
    if cause := check_t4(state.assumption_registry, state.assumption_burst_threshold):
        return cause
    if cause := check_t5(state.iteration, state.budget, state.start_time, now):
        return cause
    if state.handshake_registry is not None:
        if cause := check_t6(state.handshake_registry, state.blocking_handshakes):
            return cause
    if cause := check_t7(state.provider_timeout):
        return cause
    # T8/T9 fallback: only fires if the loop controller has stored the
    # current intent text on the state (module_04 wiring). Without the
    # attribute the check is a no-op so pre-v0.5.1 callers stay green.
    # Strict mode gate: SP Q4b amendment.
    intent_text = getattr(state, "current_intent_text", None)
    strict = getattr(state, "strict_prompt_digest", False)
    if intent_text is not None:
        if cause := check_t8(state.suite, intent_text, strict=strict):
            return cause
    return None


# ---------------------------------------------------------------------------
# Factory: persist the suite before the first step executes.
# ---------------------------------------------------------------------------


def build_loop_state(
    *,
    plan: Plan,
    workspace: WorkspaceSnapshot,
    suite: AcceptanceSuite,
    run_dir: Path | str | None = None,
    **kwargs: Any,
) -> LoopState:
    """Construct a ``LoopState`` and persist ``suite.json`` before returning.

    When ``run_dir`` is provided, the canonical serialization of the suite
    is written to ``<run_dir>/suite.json`` **before** the ``LoopState`` is
    returned to the caller. That ordering is the guarantee module_01 makes:
    the compile artifact is on disk before any step-write path can run.

    See ``docs/ARCHITECTURE.md``, section "Acceptance suite compiled before
    loop entry" and ADR-0010.
    """
    if run_dir is not None:
        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        suite_path = run_path / "suite.json"
        suite_path.write_text(suite.to_json(), encoding="utf-8")
        # v0.5.1 module_04 SP Q5b amendment (external reviewer DEFECT
        # verdict, both agreed): eagerly record the initial suite as
        # chain entry 0 at build time so a run that never recompiles
        # still leaves an immutable audit trail. Without this, an
        # attacker who mutates ``suite.json`` directly (bypassing the
        # compiler) leaves no chain evidence -- the drift check would
        # fall back to the mutated ``state.suite.prompt_digest`` and
        # accept the attacker's intent.
        prompt_digest = getattr(suite, "prompt_digest", None)
        if prompt_digest is not None:
            try:
                from ract.core.suite_chain import SuiteChain

                chain = SuiteChain(run_path)
                if not chain.entries():
                    # v0.5.1 module_06: run_id resolution order --
                    # (1) ambient run_id (:func:`ract.runtime.get_current_run_id`),
                    # (2) ``run_dir/run_id.txt`` marker file,
                    # (3) ``run_dir.name`` basename fallback. The ambient
                    # takes precedence because it is the value the loop
                    # controller bound at ``run()`` entry; the marker
                    # file exists mostly to bootstrap runs from disk
                    # (e.g., an operator-driven ``intent recompile``
                    # invoked from a shell without an active loop).
                    from ract.runtime import get_current_run_id

                    run_id = get_current_run_id() or ""
                    if not run_id:
                        marker = run_path / "run_id.txt"
                        if marker.exists():
                            try:
                                run_id = marker.read_text(encoding="utf-8").strip()
                            except OSError:
                                run_id = run_path.name
                        else:
                            run_id = run_path.name
                    chain.append(
                        prompt_digest=prompt_digest,
                        suite_digest=suite.digest(),
                        run_id=run_id or run_path.name,
                        origin="initial",
                        rootknot_signature=None,
                    )
            except Exception:  # noqa: BLE001 -- chain write must never break loop entry
                pass
    return LoopState(plan=plan, workspace=workspace, suite=suite, **kwargs)


def load_suite_from_run_dir(run_dir: Path | str) -> AcceptanceSuite:
    """Read ``<run_dir>/suite.json`` and deserialize it."""
    # Import here to keep the module surface tight and avoid a cycle if the
    # reader ever grows dependencies on loop primitives.
    from ract.core.predicate import suite_from_canonical

    payload = json.loads((Path(run_dir) / "suite.json").read_text(encoding="utf-8"))
    return suite_from_canonical(payload)


# RACT 0.4.0
