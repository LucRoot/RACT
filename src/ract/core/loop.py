"""Formal recursion loop with T1–T7 termination conditions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from ract.core.assumption_registry import AssumptionRegistry
from ract.handshake_registry import HandshakeRegistry
from ract.loop_planner import Milestone
from ract.manager import Plan


class TerminationCause(Enum):
    """Why the recursion loop stopped."""

    COMPLETE = auto()  # T1: all milestones verified.
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
    """Lightweight view of the workspace at a point in time."""

    files: dict[str, str] = field(default_factory=dict)
    timestamp: float = 0.0


@dataclass
class MilestoneReport:
    """Outcome of evaluating one milestone."""

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
    """Complete state of the recursion loop."""

    plan: Plan
    workspace: WorkspaceSnapshot
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
    tau_complete: float = 0.95
    delta_regress: float = 0.1
    assumption_burst_threshold: int = 3
    blocking_handshakes: set[str] | None = None

    def __post_init__(self) -> None:
        if self.handshake_registry is None:
            self.handshake_registry = HandshakeRegistry(".")


# Default thresholds used by the predicates.
_DEFAULT_TAU_COMPLETE: float = 0.95
_DEFAULT_DELTA_REGRESS: float = 0.1
_DEFAULT_ASSUMPTION_BURST: int = 3


def check_t1(
    milestones: list[Milestone],
    reports: list[MilestoneReport],
    tau_complete: float = _DEFAULT_TAU_COMPLETE,
) -> TerminationCause | None:
    """T1: all milestones verified with confidence >= tau_complete."""
    if not milestones:
        return None
    verified = {r.milestone_id for r in reports if r.status == "verified"}
    for milestone in milestones:
        report = next((r for r in reports if r.milestone_id == milestone.id), None)
        if report is None or report.status != "verified":
            return None
        if report.confidence < tau_complete:
            return None
    if len(verified) == len(milestones):
        return TerminationCause.COMPLETE
    return None


def check_t2(
    quality_history: list[QualityScore],
    delta_regress: float = _DEFAULT_DELTA_REGRESS,
) -> TerminationCause | None:
    """T2: quality regressed by > delta_regress for two consecutive iterations."""
    if len(quality_history) < 2:
        return None
    # Look at the last two scores.
    last = quality_history[-1]
    previous = quality_history[-2]
    if previous.value - last.value > delta_regress:
        # Check if this is the second consecutive regression.
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
    """T6: unresolved handshake blocks the critical path.

    Only handshakes explicitly listed in *blocking_ids* are considered blocking.
    When *blocking_ids* is None, any pending handshake blocks.
    """
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
    if cause := check_t1(state.milestones, state.milestone_history, state.tau_complete):
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


# RACT 0.2.0
