"""Failure-record aggregation for the self-adjustment layer (module_08 step 6).

Every function failure emits a structured :class:`FailureRecord`; the
records land in ``.rack/failures/records.jsonl`` (append-only JSONL).
The aggregator groups by function and failure_type over a sliding
window and produces narrowing proposals for the budget layer.

Design notes:

- The aggregator ONLY narrows: a proposal that would widen a current
  declaration is refused at construction time (mirrors
  :class:`~ract.memory.budget.WideningRefusedError`).
- Automatic nightly application defers to v0.6 per master spec
  §Bounded scope. This module ships the aggregator + the shape a
  future scheduler will invoke; module_09 wires a manual
  ``ract memory apply-narrowings`` CLI verb.
- Privacy: :class:`FailureRecord` explicitly excludes raw prompt /
  response content by construction (Lateral Chain branch C in
  module_08.md PRE). A future request to include content is a
  schema bump plus operator handshake.
- PhaseRecord consumption (module_07 POST inbound constraint 1):
  :func:`failure_from_phase_record` returns a
  :class:`FailureRecord` when a
  :class:`~ract.memory.composition_runner.PhaseRecord` carries
  ``outcome == "raised"``. The runner's phase records are the
  primary composition-layer failure signal.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal


FAILURE_RECORDS_PATH: Path = Path(".rack") / "failures" / "records.jsonl"
"""Relative location of the shipped failure records file."""

APPLIED_NARROWINGS_PATH: Path = Path(".rack") / "failures" / "applied_narrowings.jsonl"
"""Relative location of the applied-narrowing audit trail (module_08 Lateral E)."""


FailureType = Literal[
    "budget_exceeded",
    "provider_error",
    "contract_error",
    "phase_raised",
    "empty_research",
    "oversized_research",
    "invalid_syntax",
    "bounded_context",
    "infeasible_plan",
    "unconfirmed_bug",
    "oversize_target",
    "iteration_bound_exceeded",
]
"""Closed vocabulary of failure kinds. Anything outside this set refuses at construct time."""


ResolutionLevel = Literal[
    "none",
    "level_1_format_downgrade",
    "level_2_scope_narrow",
    "level_3_plan_split",
    "level_4_escalation",
]
"""Closed vocabulary of resolution outcomes per master spec §Overflow handling."""


_FAILURE_TYPES: frozenset[str] = frozenset(
    {
        "budget_exceeded",
        "provider_error",
        "contract_error",
        "phase_raised",
        "empty_research",
        "oversized_research",
        "invalid_syntax",
        "bounded_context",
        "infeasible_plan",
        "unconfirmed_bug",
        "oversize_target",
        "iteration_bound_exceeded",
    }
)

_RESOLUTION_LEVELS: frozenset[str] = frozenset(
    {
        "none",
        "level_1_format_downgrade",
        "level_2_scope_narrow",
        "level_3_plan_split",
        "level_4_escalation",
    }
)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FailureRecord:
    """One structured record per function failure.

    Fields:

    - ``function`` — name of the function that failed (intake,
      research, plan, edit, or a playbook phase name).
    - ``input_token_count`` — approximate size of the assembled input
      at failure time.
    - ``output_token_count`` — approximate size of the output actually
      produced (zero when the failure fired before any output).
    - ``failure_type`` — one of :data:`_FAILURE_TYPES`.
    - ``resolution_level_reached`` — one of :data:`_RESOLUTION_LEVELS`.
    - ``timestamp`` — POSIX seconds when the failure was recorded.

    The dataclass carries NO prompt / response content by design
    (Lateral Chain branch C in module_08.md PRE).
    """

    function: str
    input_token_count: int
    output_token_count: int
    failure_type: FailureType
    resolution_level_reached: ResolutionLevel
    timestamp: int

    def __post_init__(self) -> None:
        if not isinstance(self.function, str) or not self.function:
            raise ValueError("FailureRecord.function must be a non-empty string")
        for name in ("input_token_count", "output_token_count", "timestamp"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(
                    f"FailureRecord.{name} must be int; got {type(value).__name__}"
                )
            if value < 0:
                raise ValueError(f"FailureRecord.{name} must be non-negative")
        if self.failure_type not in _FAILURE_TYPES:
            raise ValueError(
                f"FailureRecord.failure_type {self.failure_type!r} not in "
                f"{sorted(_FAILURE_TYPES)!r}"
            )
        if self.resolution_level_reached not in _RESOLUTION_LEVELS:
            raise ValueError(
                f"FailureRecord.resolution_level_reached "
                f"{self.resolution_level_reached!r} not in "
                f"{sorted(_RESOLUTION_LEVELS)!r}"
            )


@dataclass(frozen=True)
class NarrowingProposal:
    """One narrowing proposal emitted by the aggregator.

    Emitted rather than applied. The narrowing itself is only realised
    against a live :class:`~ract.memory.budget.BudgetDeclaration` at
    ``apply-narrowings`` time (module_09 wires the CLI verb).
    ``new_value`` is guaranteed ``<= reference_current_value`` at
    construction time; a proposal that would widen refuses.

    ``reason`` is a short human-readable string a downstream reader
    or CLI prints to explain WHY the proposal fired (e.g.
    ``"3 budget_exceeded failures in window of 7 days"``).
    """

    function: str
    field_name: str
    new_value: int
    reference_current_value: int
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.function, str) or not self.function:
            raise ValueError("NarrowingProposal.function must be a non-empty string")
        if not isinstance(self.field_name, str) or not self.field_name:
            raise ValueError("NarrowingProposal.field_name must be a non-empty string")
        for name in ("new_value", "reference_current_value"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(
                    f"NarrowingProposal.{name} must be int; got {type(value).__name__}"
                )
            if value < 0:
                raise ValueError(f"NarrowingProposal.{name} must be non-negative")
        if self.new_value > self.reference_current_value:
            raise ValueError(
                f"NarrowingProposal refuses widening: "
                f"new_value={self.new_value} > "
                f"reference_current_value={self.reference_current_value}"
            )


@dataclass(frozen=True)
class AggregateReport:
    """Aggregate output of :func:`aggregate` over a window.

    ``proposals`` — tuple of :class:`NarrowingProposal` records ready
    for the apply verb.

    ``counts_by_function_and_type`` — nested map: ``{function:
    {failure_type: count}}``. Callers inspect this to understand the
    aggregation without re-reading the JSONL.

    ``window_start`` / ``window_end`` — POSIX seconds bounding the
    included records.

    ``total_records_considered`` — count of records inside the window.
    """

    proposals: tuple[NarrowingProposal, ...]
    counts_by_function_and_type: dict[str, dict[str, int]]
    window_start: int
    window_end: int
    total_records_considered: int


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def write(record: FailureRecord, root: Path) -> Path:
    """Append ``record`` as one JSONL line under ``root``.

    File resides at ``root / FAILURE_RECORDS_PATH``. Parent dirs are
    created on demand. Each call appends ONE line (JSONL invariant).
    """
    target = root / FAILURE_RECORDS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(record), sort_keys=True) + "\n"
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(line)
    return target


def read_all(root: Path) -> list[FailureRecord]:
    """Return every record stored under ``root``, in file order.

    Malformed lines raise :class:`ValueError` naming the line
    number. Missing file returns an empty list (fresh install).
    """
    target = root / FAILURE_RECORDS_PATH
    if not target.is_file():
        return []
    records: list[FailureRecord] = []
    text = target.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"malformed JSON on line {lineno} of {target}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(
                f"line {lineno} of {target} is not a JSON object; "
                f"got {type(payload).__name__}"
            )
        try:
            records.append(
                FailureRecord(
                    function=payload["function"],
                    input_token_count=payload["input_token_count"],
                    output_token_count=payload["output_token_count"],
                    failure_type=payload["failure_type"],
                    resolution_level_reached=payload["resolution_level_reached"],
                    timestamp=payload["timestamp"],
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"line {lineno} of {target} is not a valid FailureRecord: {exc}"
            ) from exc
    return records


# ---------------------------------------------------------------------------
# PhaseRecord bridge
# ---------------------------------------------------------------------------


def failure_from_phase_record(
    phase_record: Any, *, now: int | None = None
) -> FailureRecord | None:
    """Convert a :class:`~ract.memory.composition_runner.PhaseRecord` to a
    :class:`FailureRecord`, or ``None`` when the phase did not fail.

    Only phases with ``outcome == "raised"`` produce a record. The
    ``function`` field carries the phase's verb name; token counts
    default to zero because the PhaseRecord shape does not carry
    them today (module_09's provider adapter is the natural home
    for populating those fields). The failure_type is derived from
    the phase notes when they name a known error family; falls back
    to ``"phase_raised"``.

    Module_07 POST inbound constraint 1 pinned here.
    """
    outcome = getattr(phase_record, "outcome", None)
    if outcome != "raised":
        return None
    function = getattr(phase_record, "function", None) or getattr(
        phase_record, "phase_name", ""
    )
    if not function:
        raise ValueError("phase_record must carry a non-empty function or phase_name")
    notes = getattr(phase_record, "notes", ()) or ()
    failure_type = _classify_phase_failure_from_notes(notes)
    return FailureRecord(
        function=str(function),
        input_token_count=0,
        output_token_count=0,
        failure_type=failure_type,
        resolution_level_reached="none",
        timestamp=int(now if now is not None else time.time()),
    )


def _classify_phase_failure_from_notes(notes: tuple[str, ...]) -> FailureType:
    """Map phase notes to a specific :data:`FailureType` when recognisable.

    Falls back to ``"phase_raised"`` when the notes do not name a
    known error family. Notes are advisory strings emitted by the
    composition runner (`_run_reproduce_phase`, etc.), not
    structured taxonomy.
    """
    joined = " ".join(notes).casefold()
    if "reproduce" in joined and "did not reproduce" in joined:
        return "unconfirmed_bug"
    if "reproduce" in joined and "no command available" in joined:
        return "unconfirmed_bug"
    if "iteration" in joined and "bound" in joined:
        return "iteration_bound_exceeded"
    if "oversize" in joined and "target" in joined:
        return "oversize_target"
    return "phase_raised"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


DEFAULT_WINDOW_DAYS: int = 7
"""Sliding window in days over which the aggregator groups records."""

REPEATED_FAILURE_THRESHOLD: int = 3
"""How many failures of the same (function, failure_type) trigger a proposal."""

NARROWING_STEP_FRACTION: float = 0.8
"""Multiplier applied to the reference value; 0.8 = 20% narrowing per proposal."""


# Which failure kinds map to which budget field for narrowing.
_FAILURE_NARROWING_MAP: dict[str, str] = {
    "budget_exceeded": "input_target",
    "bounded_context": "input_target",
    "oversized_research": "input_target",
    "oversize_target": "input_target",
    "invalid_syntax": "output_target",
    "iteration_bound_exceeded": "input_target",
}


def aggregate(
    root: Path,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: int | None = None,
    current_budgets: dict[tuple[str, str], int] | None = None,
) -> AggregateReport:
    """Aggregate records under ``root`` into narrowing proposals.

    ``window_days`` — records older than this are excluded.

    ``now`` — POSIX seconds treated as "now" for the window
    comparison. Defaults to :func:`time.time`.

    ``current_budgets`` — map from ``(function, field_name)`` to the
    current value of that field on the live declaration. When
    ``None`` the aggregator uses each record's ``input_token_count``
    as the reference value (a conservative fallback that still
    guarantees the always-narrowing invariant). Callers with access
    to the live budget registry are expected to supply this map so
    the proposals reference the real current declaration.

    Returns an :class:`AggregateReport`. The proposal set is
    deterministic given the input records and the ``now`` cutoff.
    """
    if window_days <= 0:
        raise ValueError(f"window_days must be positive; got {window_days!r}")
    end = int(now if now is not None else time.time())
    start = end - window_days * 86400
    all_records = read_all(root)
    in_window = [rec for rec in all_records if start <= rec.timestamp <= end]

    counts: dict[str, dict[str, int]] = {}
    ref_values_by_pair: dict[tuple[str, str], int] = {}
    for rec in in_window:
        counts.setdefault(rec.function, {}).setdefault(rec.failure_type, 0)
        counts[rec.function][rec.failure_type] += 1
        field_name = _FAILURE_NARROWING_MAP.get(rec.failure_type)
        if field_name is None:
            continue
        # Track the max input_token_count seen at failure for this
        # (function, field) pair. The proposal narrows against the
        # supplied current_budgets when available; otherwise falls
        # back to this observed max.
        key = (rec.function, field_name)
        prior = ref_values_by_pair.get(key, 0)
        if rec.input_token_count > prior:
            ref_values_by_pair[key] = rec.input_token_count

    proposals: list[NarrowingProposal] = []
    for function, per_type in sorted(counts.items()):
        for failure_type, count in sorted(per_type.items()):
            if count < REPEATED_FAILURE_THRESHOLD:
                continue
            field_name = _FAILURE_NARROWING_MAP.get(failure_type)
            if field_name is None:
                continue
            supplied = None
            if current_budgets is not None:
                supplied = current_budgets.get((function, field_name))
            reference = (
                supplied
                if supplied is not None
                else ref_values_by_pair.get((function, field_name), 0)
            )
            if reference <= 0:
                continue
            proposed_new = int(reference * NARROWING_STEP_FRACTION)
            if proposed_new >= reference:
                # Rounding collapse (reference already tiny).
                proposed_new = max(0, reference - 1)
            proposals.append(
                NarrowingProposal(
                    function=function,
                    field_name=field_name,
                    new_value=proposed_new,
                    reference_current_value=reference,
                    reason=(
                        f"{count} {failure_type} failure(s) in window of "
                        f"{window_days} days"
                    ),
                )
            )

    return AggregateReport(
        proposals=tuple(proposals),
        counts_by_function_and_type={
            fn: dict(per_type) for fn, per_type in counts.items()
        },
        window_start=start,
        window_end=end,
        total_records_considered=len(in_window),
    )


class StaleReferenceError(RuntimeError):
    """Raised when a proposal's reference disagrees with the live budget.

    Second Pass Q4 Orthogonal 3: the aggregator's
    ``NarrowingProposal.__post_init__`` refuses widening against
    ``reference_current_value``. If the caller supplied a STALE
    (too-high) reference at ``aggregate()`` time and the live budget
    is smaller, applying the proposal against the live budget could
    silently widen. :func:`validate_proposal_against_live_value`
    re-checks the proposal against the live current value at apply
    time and raises here on any drift.
    """


def validate_proposal_against_live_value(
    proposal: NarrowingProposal,
    live_current_value: int,
) -> None:
    """Refuse a proposal that would widen against the LIVE current value.

    Second Pass Q4 Orthogonal 3 safety gate: even if the proposal's
    construction-time invariant held, the ``reference_current_value``
    it was built against might be stale. The apply verb MUST call
    this against the actual current declaration before writing.
    Raises :class:`StaleReferenceError` on stale reference or on any
    widening attempt against the live value.
    """
    if not isinstance(live_current_value, int) or isinstance(live_current_value, bool):
        raise TypeError(
            f"live_current_value must be int; got {type(live_current_value).__name__}"
        )
    if live_current_value < 0:
        raise ValueError(
            f"live_current_value must be non-negative; got {live_current_value!r}"
        )
    if proposal.new_value > live_current_value:
        raise StaleReferenceError(
            f"proposal for {proposal.function}.{proposal.field_name}: "
            f"new_value={proposal.new_value} > live_current_value="
            f"{live_current_value} (proposal.reference_current_value="
            f"{proposal.reference_current_value}); stale reference or "
            f"live budget shrank since aggregation"
        )


def append_applied_narrowing(
    proposal: NarrowingProposal,
    root: Path,
    *,
    applied_at: int | None = None,
    operator_note: str = "",
    live_current_value: int | None = None,
) -> Path:
    """Append one applied-narrowing audit line under ``root``.

    Lateral Chain branch E in module_08.md PRE: every applied
    narrowing is logged for later audit so the operator can inspect
    what the ``apply-narrowings`` verb actually did.

    Second Pass Q4 Orthogonal 3 safety gate: when ``live_current_value``
    is supplied, :func:`validate_proposal_against_live_value` runs
    first and refuses stale-reference widening. Module_09's shipped
    apply verb MUST pass the live value; a ``None`` here is
    tolerated for the audit-only path but is not the intended shape.
    """
    if live_current_value is not None:
        validate_proposal_against_live_value(proposal, live_current_value)
    target = root / APPLIED_NARROWINGS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "function": proposal.function,
        "field_name": proposal.field_name,
        "old": proposal.reference_current_value,
        "new": proposal.new_value,
        "reason": proposal.reason,
        "operator_note": operator_note,
        "applied_at": int(applied_at if applied_at is not None else time.time()),
    }
    line = json.dumps(payload, sort_keys=True) + "\n"
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(line)
    return target


def rewrite_records_atomic(records: list[FailureRecord], root: Path) -> Path:
    """Rewrite the JSONL under ``root`` atomically.

    Used by v0.6's compaction pass. Kept here so the write path is
    consistent with the capability record's atomic-replace semantics
    (Second Pass Q4).
    """
    target = root / FAILURE_RECORDS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix="records-",
        suffix=".jsonl.tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for rec in records:
                handle.write(json.dumps(asdict(rec), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return target


__all__ = [
    "APPLIED_NARROWINGS_PATH",
    "AggregateReport",
    "DEFAULT_WINDOW_DAYS",
    "FAILURE_RECORDS_PATH",
    "FailureRecord",
    "FailureType",
    "NARROWING_STEP_FRACTION",
    "NarrowingProposal",
    "REPEATED_FAILURE_THRESHOLD",
    "ResolutionLevel",
    "StaleReferenceError",
    "aggregate",
    "append_applied_narrowing",
    "failure_from_phase_record",
    "read_all",
    "rewrite_records_atomic",
    "validate_proposal_against_live_value",
    "write",
]


from ract.core.module_identity import _module_knot, register_module_knot  # noqa: E402


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
