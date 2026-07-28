"""Formal recursion loop with T1–T7 termination conditions.

v0.4 change (SUBSTRATE §2 and §11 signals 1–2): T1 (Completion) is now a
fact about the environment. ``LoopState`` carries a frozen
``AcceptanceSuite``; ``check_t1`` returns ``COMPLETE`` only when every
required predicate evaluates ``ok=True`` against the workspace snapshot.
The milestone-oracle path is retained for scheduling/reporting only; no
model opinion terminates the loop.

Rationale in ``docs/ADRs/ADR-0010-acceptance-predicates.md``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ract.core.assumption_registry import AssumptionRegistry
from ract.core.predicate import AcceptanceSuite
from ract.handshake_registry import HandshakeRegistry
from ract.loop_planner import Milestone
from ract.manager import Plan

if TYPE_CHECKING:
    pass


class TerminationCause(Enum):
    """Why the recursion loop stopped."""

    COMPLETE = auto()  # T1: all required predicates evaluate ok against the snapshot.
    REGRESSED = auto()  # T2: quality regressed twice consecutively.
    PROVENANCE_FAILURE = auto()  # T3: RK-1 or RK-2 violated.
    ASSUMPTION_BURST = auto()  # T4: too many assumptions violated.
    BUDGET_EXHAUSTED = auto()  # T5: iteration or wall-time budget exhausted.
    HANDSHAKE_BLOCKED = auto()  # T6: unresolved blocking handshake.
    PROVIDER_TIMEOUT = auto()  # T7: provider timeout twice consecutively.


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


def evaluate_termination(state: LoopState, now: float) -> TerminationCause | None:
    """Evaluate T1–T7 in order and return the first cause that fires."""
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
    return LoopState(plan=plan, workspace=workspace, suite=suite, **kwargs)


def load_suite_from_run_dir(run_dir: Path | str) -> AcceptanceSuite:
    """Read ``<run_dir>/suite.json`` and deserialize it."""
    # Import here to keep the module surface tight and avoid a cycle if the
    # reader ever grows dependencies on loop primitives.
    from ract.core.predicate import suite_from_canonical

    payload = json.loads((Path(run_dir) / "suite.json").read_text(encoding="utf-8"))
    return suite_from_canonical(payload)


# RACT 0.4.0
