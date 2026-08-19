"""Playbook composition runner (v0.5.0 memory discipline, module_07).

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §Playbooks.

Four v0.5.0 playbooks compose the four function contracts (intake,
research, plan, edit) into named workflows. This module lands the
composition primitives that the shipped YAMLs at
:mod:`ract.memory.playbooks` load into:

- :class:`PlaybookSpec`: frozen record of a playbook definition.
- :class:`PhaseSpec`: one phase inside a playbook (which verb runs,
  which retrieval overrides apply, which budget narrowing applies).
- :class:`PhaseRecord`: one runtime record produced during
  :func:`run_playbook` execution.
- :class:`PlaybookResult`: the aggregate result of a run.
- :func:`run_playbook`: the composition driver itself.

Design notes:

- Every field on every dataclass is either primitive, a tuple of
  primitives, or ``None`` so canonical JSON round-trip is trivial.
- The runner does NOT reimplement any of the four function verbs. It
  calls the shipped :func:`ract.memory.functions.intake`,
  :func:`~ract.memory.functions.research`,
  :func:`~ract.memory.functions.plan`, and
  :func:`~ract.memory.functions.edit`, threading their outputs
  through the optional :class:`~ract.memory.session.SessionMemory`.
- The reproduce phase is deterministic (subprocess), not a verb. It
  refuses when the failing test either exits zero (no reproduction)
  or produces no output at all under the plan's success criteria.
- The edit_loop phase iterates over files grouped from the plan's
  ``load_manifest``. Each iteration honors the plan's
  ``iteration_bound``: a loop past the bound raises
  :class:`IterationBoundExceededError` (Lateral Chain branch E,
  module_07 PRE).

Errors here all subclass
:class:`ract.memory.functions.errors.MemoryFunctionError` so a
composition caller can catch the family once and dispatch per
subclass.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.budget_registry import get as budget_get
from ract.memory.composition import apply_composition_override
from ract.memory.events import EventSink, NullEventSink, emit_budget_declared
from ract.memory.functions import (
    CandidateDiff,
    ChangePlan,
    IndexBundle,
    IntakeContext,
    MemoryFunctionError,
    MemoryFunctionProvider,
    ResearchBundle,
    SymbolRef,
    WorkOrder,
    edit as edit_fn,
    intake as intake_fn,
    plan as plan_fn,
    research as research_fn,
)
from ract.memory.session import SessionMemory


# ---------------------------------------------------------------------------
# Playbook error family
# ---------------------------------------------------------------------------


class UnknownPlaybookError(MemoryFunctionError):
    """Raised when a caller asks for a playbook name that is not shipped.

    Payload carries the requested name plus the sorted list of names
    the runner did ship, so the caller sees the offered surface in
    the same message.
    """


class PlaybookSchemaError(MemoryFunctionError):
    """Raised when a playbook YAML has an unknown field or wrong shape.

    A typo like ``per_iteration_bugdet`` (or a missing required key
    like ``phases``) surfaces here rather than silently defaulting.
    The payload names the offending field path so the fix is
    unambiguous.
    """


class UnconfirmedBugError(MemoryFunctionError):
    """Raised by the bug_fix reproduce phase when no failing reproduction is confirmed.

    Two shapes trigger the raise:

    1. The reproduce command exits zero (the "failing" test passes,
       so there is nothing to reproduce).
    2. No reproduce command is available (neither the playbook nor
       the WorkOrder's ``success_criteria`` yields runnable pytest
       node ids), so we cannot know if the bug reproduces at all.

    Master spec §Bug fix and module_07 Lateral Chain branch A: a
    bug fix without a confirmed reproduction is refused, not
    silently attempted.
    """


class OversizeTargetError(MemoryFunctionError):
    """Raised by the extract playbook when the target function alone busts budget.

    Extract-method's edit phase pins its target function at FULL
    format (module_07 Lateral Chain branch C); if even the target
    exceeds the input budget, the operator must reduce the function
    before extraction is attempted. The runner surfaces this as
    :class:`OversizeTargetError` naming the target.
    """


class IterationBoundExceededError(MemoryFunctionError):
    """Raised by edit_loop when the number of iterations exceeds the plan bound.

    Master spec §edit + module_07 Lateral Chain branch E:
    ``ChangePlan.iteration_bound`` caps the plan-edit outer loop.
    A rename that touches 50 files under an iteration_bound of 10
    surfaces here rather than firing 50 model calls silently.
    """


# ---------------------------------------------------------------------------
# Playbook shape
# ---------------------------------------------------------------------------


_PHASE_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "function",
        "retrieval_overrides",
        "budget_override",
        "split_threshold",
        "per_iteration_budget",
        "max_iterations",
        "reproduce_command",
    }
)

_PHASE_REQUIRED_FIELDS: frozenset[str] = frozenset({"name", "function"})

_PLAYBOOK_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {"name", "version", "description", "phases"}
)

_PLAYBOOK_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"name", "version", "description", "phases"}
)

_LEGAL_PHASE_FUNCTIONS: frozenset[str] = frozenset(
    {"intake", "research", "plan", "edit", "reproduce"}
)


@dataclass(frozen=True)
class PhaseSpec:
    """One phase inside a playbook.

    ``function`` names the verb this phase runs. ``reproduce`` is the
    only deterministic (non-model) phase. ``retrieval_overrides`` is
    a tuple of ``(key, value)`` pairs the runner forwards to the
    matching function's retrieval hints (as strings; the function
    parses). ``budget_override`` is a tuple of ``(field_name,
    int_value)`` narrowings applied via
    :func:`~ract.memory.composition.apply_composition_override`
    before the phase's model call.
    """

    name: str
    function: str
    retrieval_overrides: tuple[tuple[str, str], ...] = ()
    budget_override: tuple[tuple[str, int], ...] = ()
    split_threshold: int | None = None
    per_iteration_budget: int | None = None
    max_iterations: int | None = None
    reproduce_command: str | None = None


@dataclass(frozen=True)
class PlaybookSpec:
    """A playbook definition loaded from YAML.

    ``phases`` is executed in list order. Duplicate phase names raise
    :class:`PlaybookSchemaError` at load time. Legal ``function``
    values live in :data:`_LEGAL_PHASE_FUNCTIONS`.
    """

    name: str
    version: int
    description: str
    phases: tuple[PhaseSpec, ...]


@dataclass(frozen=True)
class PhaseRecord:
    """One runtime record per executed phase.

    ``outcome`` is ``"ok"`` when the phase ran to completion,
    ``"escalated"`` when the phase deliberately stopped (e.g. no
    manifest for edit_loop), or ``"raised"`` when the phase's verb
    raised an exception the runner re-raised. ``notes`` carries
    per-phase advisory strings (ambiguity flags, cascade
    downgrades, iteration counts) that a downstream reader inspects
    for provenance.
    """

    phase_name: str
    function: str
    duration_ms: int
    outcome: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlaybookResult:
    """Aggregate result of :func:`run_playbook`.

    ``edits`` is a tuple: single-edit playbooks return one entry;
    edit_loop returns one per grouped file. ``phase_records`` covers
    every phase that ran, in execution order.
    """

    work_order: WorkOrder
    research: ResearchBundle
    plan: ChangePlan
    edits: tuple[CandidateDiff, ...]
    phase_records: tuple[PhaseRecord, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# YAML parsing
# ---------------------------------------------------------------------------


def parse_playbook_payload(payload: Any, *, source_label: str) -> PlaybookSpec:
    """Return a :class:`PlaybookSpec` for ``payload`` or raise :class:`PlaybookSchemaError`.

    ``source_label`` names the on-disk file (or ``"<in-memory>"``)
    so the error message points a reader to the offending YAML.
    """
    if not isinstance(payload, dict):
        raise PlaybookSchemaError(
            f"playbook {source_label!r} top-level must be a mapping; "
            f"got {type(payload).__name__}",
            function="playbook_load",
            payload={"source": source_label},
        )
    unknown = set(payload) - _PLAYBOOK_ALLOWED_FIELDS
    if unknown:
        raise PlaybookSchemaError(
            f"playbook {source_label!r} has unknown top-level fields: "
            f"{sorted(unknown)!r}",
            function="playbook_load",
            payload={"source": source_label, "unknown_fields": sorted(unknown)},
        )
    missing = _PLAYBOOK_REQUIRED_FIELDS - set(payload)
    if missing:
        raise PlaybookSchemaError(
            f"playbook {source_label!r} missing required fields: {sorted(missing)!r}",
            function="playbook_load",
            payload={"source": source_label, "missing_fields": sorted(missing)},
        )
    name_raw = payload["name"]
    if not isinstance(name_raw, str) or not name_raw:
        raise PlaybookSchemaError(
            f"playbook {source_label!r} field 'name' must be a non-empty string",
            function="playbook_load",
            payload={"source": source_label},
        )
    version_raw = payload["version"]
    if not isinstance(version_raw, int) or isinstance(version_raw, bool):
        raise PlaybookSchemaError(
            f"playbook {source_label!r} field 'version' must be an int; "
            f"got {type(version_raw).__name__}",
            function="playbook_load",
            payload={"source": source_label},
        )
    description_raw = payload["description"]
    if not isinstance(description_raw, str):
        raise PlaybookSchemaError(
            f"playbook {source_label!r} field 'description' must be a string",
            function="playbook_load",
            payload={"source": source_label},
        )
    phases_raw = payload["phases"]
    if not isinstance(phases_raw, list) or not phases_raw:
        raise PlaybookSchemaError(
            f"playbook {source_label!r} field 'phases' must be a non-empty list",
            function="playbook_load",
            payload={"source": source_label},
        )
    phases: list[PhaseSpec] = []
    seen_names: set[str] = set()
    for i, entry in enumerate(phases_raw):
        phase = _parse_phase_entry(entry, index=i, source_label=source_label)
        if phase.name in seen_names:
            raise PlaybookSchemaError(
                f"playbook {source_label!r} phases[{i}] duplicates name {phase.name!r}",
                function="playbook_load",
                payload={"source": source_label, "phase_name": phase.name},
            )
        seen_names.add(phase.name)
        phases.append(phase)
    return PlaybookSpec(
        name=name_raw,
        version=version_raw,
        description=description_raw,
        phases=tuple(phases),
    )


def _parse_phase_entry(entry: Any, *, index: int, source_label: str) -> PhaseSpec:
    if not isinstance(entry, dict):
        raise PlaybookSchemaError(
            f"playbook {source_label!r} phases[{index}] must be a mapping; "
            f"got {type(entry).__name__}",
            function="playbook_load",
            payload={"source": source_label, "phase_index": index},
        )
    unknown = set(entry) - _PHASE_ALLOWED_FIELDS
    if unknown:
        raise PlaybookSchemaError(
            f"playbook {source_label!r} phases[{index}] has unknown fields: "
            f"{sorted(unknown)!r}",
            function="playbook_load",
            payload={
                "source": source_label,
                "phase_index": index,
                "unknown_fields": sorted(unknown),
            },
        )
    missing = _PHASE_REQUIRED_FIELDS - set(entry)
    if missing:
        raise PlaybookSchemaError(
            f"playbook {source_label!r} phases[{index}] missing required fields: "
            f"{sorted(missing)!r}",
            function="playbook_load",
            payload={
                "source": source_label,
                "phase_index": index,
                "missing_fields": sorted(missing),
            },
        )
    name_raw = entry["name"]
    if not isinstance(name_raw, str) or not name_raw:
        raise PlaybookSchemaError(
            f"playbook {source_label!r} phases[{index}].name must be a non-empty string",
            function="playbook_load",
            payload={"source": source_label, "phase_index": index},
        )
    function_raw = entry["function"]
    if function_raw not in _LEGAL_PHASE_FUNCTIONS:
        raise PlaybookSchemaError(
            f"playbook {source_label!r} phases[{index}].function must be one of "
            f"{sorted(_LEGAL_PHASE_FUNCTIONS)!r}; got {function_raw!r}",
            function="playbook_load",
            payload={"source": source_label, "phase_index": index},
        )
    retrieval_overrides = _parse_string_map(
        entry.get("retrieval_overrides"),
        field_path=f"phases[{index}].retrieval_overrides",
        source_label=source_label,
    )
    budget_override = _parse_budget_override(
        entry.get("budget_override"),
        field_path=f"phases[{index}].budget_override",
        source_label=source_label,
    )
    split_threshold = _parse_optional_int(
        entry.get("split_threshold"),
        field_path=f"phases[{index}].split_threshold",
        source_label=source_label,
    )
    per_iteration_budget = _parse_optional_int(
        entry.get("per_iteration_budget"),
        field_path=f"phases[{index}].per_iteration_budget",
        source_label=source_label,
    )
    max_iterations = _parse_optional_int(
        entry.get("max_iterations"),
        field_path=f"phases[{index}].max_iterations",
        source_label=source_label,
    )
    reproduce_command_raw = entry.get("reproduce_command")
    if reproduce_command_raw is not None and not isinstance(reproduce_command_raw, str):
        raise PlaybookSchemaError(
            f"playbook {source_label!r} phases[{index}].reproduce_command must be "
            f"a string or omitted; got {type(reproduce_command_raw).__name__}",
            function="playbook_load",
            payload={"source": source_label, "phase_index": index},
        )
    return PhaseSpec(
        name=name_raw,
        function=function_raw,
        retrieval_overrides=retrieval_overrides,
        budget_override=budget_override,
        split_threshold=split_threshold,
        per_iteration_budget=per_iteration_budget,
        max_iterations=max_iterations,
        reproduce_command=reproduce_command_raw,
    )


def _parse_string_map(
    raw: Any, *, field_path: str, source_label: str
) -> tuple[tuple[str, str], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise PlaybookSchemaError(
            f"playbook {source_label!r} {field_path} must be a mapping; "
            f"got {type(raw).__name__}",
            function="playbook_load",
            payload={"source": source_label, "field": field_path},
        )
    out: list[tuple[str, str]] = []
    for key, value in raw.items():
        if not isinstance(key, str):
            raise PlaybookSchemaError(
                f"playbook {source_label!r} {field_path} key must be a string; "
                f"got {type(key).__name__}",
                function="playbook_load",
                payload={"source": source_label, "field": field_path},
            )
        out.append((key, str(value)))
    return tuple(sorted(out))


def _parse_budget_override(
    raw: Any, *, field_path: str, source_label: str
) -> tuple[tuple[str, int], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        raise PlaybookSchemaError(
            f"playbook {source_label!r} {field_path} must be a mapping; "
            f"got {type(raw).__name__}",
            function="playbook_load",
            payload={"source": source_label, "field": field_path},
        )
    out: list[tuple[str, int]] = []
    for key, value in raw.items():
        if not isinstance(key, str):
            raise PlaybookSchemaError(
                f"playbook {source_label!r} {field_path} key must be a string; "
                f"got {type(key).__name__}",
                function="playbook_load",
                payload={"source": source_label, "field": field_path},
            )
        if isinstance(value, bool) or not isinstance(value, int):
            raise PlaybookSchemaError(
                f"playbook {source_label!r} {field_path}.{key} must be an int; "
                f"got {type(value).__name__}: {value!r}",
                function="playbook_load",
                payload={"source": source_label, "field": f"{field_path}.{key}"},
            )
        out.append((key, value))
    return tuple(sorted(out))


def _parse_optional_int(raw: Any, *, field_path: str, source_label: str) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise PlaybookSchemaError(
            f"playbook {source_label!r} {field_path} must be an int or omitted; "
            f"got {type(raw).__name__}: {raw!r}",
            function="playbook_load",
            payload={"source": source_label, "field": field_path},
        )
    return raw


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_playbook(
    spec: PlaybookSpec,
    request: str,
    repo_root: Path,
    provider: MemoryFunctionProvider,
    indexes: IndexBundle,
    *,
    session: SessionMemory | None = None,
    sink: EventSink | None = None,
    reproduce_command: str | None = None,
    intake_context: IntakeContext | None = None,
) -> PlaybookResult:
    """Execute ``spec`` end-to-end against ``provider`` + ``indexes``.

    Sequence:

    1. Emit a ``budget.declared`` event tagged with the playbook name
       and the first phase's function so a trace reader can locate
       the run boundary.
    2. Run intake: its WorkOrder is threaded to research + plan.
       If the WorkOrder carries any ``ambiguity_flags``, a phase
       record note flags the risk marker (module_06 POST inbound
       constraint 1). The runner does NOT halt on ambiguity: the
       flag is a documented risk marker per master spec §intake
       failure modes.
    3. Run research; emit its outputs.
    4. If the playbook includes a ``reproduce`` phase, run it before
       plan. The reproduce phase is deterministic (subprocess) and
       raises :class:`UnconfirmedBugError` on non-reproducing input.
    5. Run plan; emit its ChangePlan.
    6. Run edit or edit_loop. edit_loop iterates over files grouped
       from ``plan.load_manifest``; each iteration honors
       ``ChangePlan.iteration_bound``.

    ``session`` (optional) is written after each successful phase so
    a caller can inspect the intermediate contracts on disk. The
    caller owns the ``session_path`` and its uniqueness (see
    :class:`SessionMemory` docstring).
    """
    active_sink = sink or NullEventSink()
    active_intake_context = intake_context or IntakeContext(repo_root=repo_root)
    phase_records: list[PhaseRecord] = []

    phases_by_function: dict[str, PhaseSpec] = {p.function: p for p in spec.phases}
    intake_phase = _require_phase(spec, "intake")
    research_phase = _require_phase(spec, "research")
    plan_phase = _require_phase(spec, "plan")
    edit_phase = _find_phase_by_function(spec, "edit")
    if edit_phase is None:
        raise PlaybookSchemaError(
            f"playbook {spec.name!r} missing a phase with function='edit'",
            function="playbook_run",
            payload={"playbook": spec.name},
        )
    reproduce_phase = phases_by_function.get("reproduce")

    # --- intake ---------------------------------------------------------
    work_order = _run_verb_phase(
        spec,
        intake_phase,
        lambda: intake_fn(
            request,
            active_intake_context,
            provider,
            sink=active_sink,
        ),
        active_sink,
        phase_records,
    )
    intake_notes: list[str] = []
    if work_order.ambiguity_flags:
        flags = ", ".join(work_order.ambiguity_flags)
        intake_notes.append(f"ambiguity_flag: proceeding with risk marker ({flags})")
        emit_budget_declared(
            active_sink,
            {
                "function": "playbook",
                "playbook": spec.name,
                "phase": intake_phase.name,
                "ambiguity_flags": list(work_order.ambiguity_flags),
                "source": "composition",
            },
        )
    if intake_notes:
        phase_records[-1] = _append_notes(phase_records[-1], intake_notes)
    if session is not None:
        session.set_work_order(work_order)

    # --- research -------------------------------------------------------
    research_bundle = _run_verb_phase(
        spec,
        research_phase,
        lambda: research_fn(work_order, indexes, provider, sink=active_sink),
        active_sink,
        phase_records,
    )
    if session is not None:
        session.set_research_bundle(research_bundle)

    # --- reproduce (optional) ------------------------------------------
    if reproduce_phase is not None:
        _run_reproduce_phase(
            reproduce_phase,
            work_order,
            repo_root,
            spec_name=spec.name,
            phase_records=phase_records,
            sink=active_sink,
            reproduce_command=reproduce_command,
        )

    # --- plan -----------------------------------------------------------
    change_plan = _run_verb_phase(
        spec,
        plan_phase,
        lambda: plan_fn(
            work_order,
            research_bundle,
            indexes,
            provider,
            sink=active_sink,
        ),
        active_sink,
        phase_records,
    )
    plan_notes: list[str] = []
    if plan_phase.split_threshold is not None:
        file_count = len({ref.file_path for ref in change_plan.load_manifest})
        if file_count > plan_phase.split_threshold:
            plan_notes.append(
                f"split_advisory: load_manifest file count {file_count} "
                f"exceeds split_threshold {plan_phase.split_threshold}"
            )
    if plan_notes:
        phase_records[-1] = _append_notes(phase_records[-1], plan_notes)
    if session is not None:
        session.set_change_plan(change_plan)

    # --- edit or edit_loop ---------------------------------------------
    edits: list[CandidateDiff]
    if edit_phase.name == "edit_loop" or edit_phase.per_iteration_budget is not None:
        edits = _run_edit_loop(
            spec,
            edit_phase,
            change_plan,
            indexes,
            provider,
            sink=active_sink,
            phase_records=phase_records,
        )
    else:
        edits = [
            _run_edit_single(
                spec,
                edit_phase,
                change_plan,
                indexes,
                provider,
                sink=active_sink,
                phase_records=phase_records,
            )
        ]
    if session is not None and edits:
        session.set_candidate_diff(edits[0])

    return PlaybookResult(
        work_order=work_order,
        research=research_bundle,
        plan=change_plan,
        edits=tuple(edits),
        phase_records=tuple(phase_records),
    )


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------


def _require_phase(spec: PlaybookSpec, function: str) -> PhaseSpec:
    phase = _find_phase_by_function(spec, function)
    if phase is None:
        raise PlaybookSchemaError(
            f"playbook {spec.name!r} missing a phase with function={function!r}",
            function="playbook_run",
            payload={"playbook": spec.name, "expected_function": function},
        )
    return phase


def _find_phase_by_function(spec: PlaybookSpec, function: str) -> PhaseSpec | None:
    for phase in spec.phases:
        if phase.function == function:
            return phase
    return None


def _run_verb_phase(
    spec: PlaybookSpec,
    phase: PhaseSpec,
    verb: Any,
    sink: EventSink,
    phase_records: list[PhaseRecord],
) -> Any:
    """Invoke ``verb`` under playbook trace + phase-record bookkeeping."""
    emit_budget_declared(
        sink,
        {
            "function": phase.function,
            "phase": phase.name,
            "playbook": spec.name,
            "source": "composition",
        },
    )
    _apply_phase_budget_override(phase)
    start = time.monotonic()
    try:
        result = verb()
    except MemoryFunctionError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        phase_records.append(
            PhaseRecord(
                phase_name=phase.name,
                function=phase.function,
                duration_ms=elapsed_ms,
                outcome="raised",
            )
        )
        raise
    elapsed_ms = int((time.monotonic() - start) * 1000)
    phase_records.append(
        PhaseRecord(
            phase_name=phase.name,
            function=phase.function,
            duration_ms=elapsed_ms,
            outcome="ok",
        )
    )
    return result


def _apply_phase_budget_override(phase: PhaseSpec) -> None:
    """Apply the phase's budget override against the registry-default declaration.

    The override is applied to a fresh copy pulled from the budget
    registry; the return value is discarded here because the function
    itself reads the registry inside its own call. Applying the
    override still exercises the composition layer for its refuse-on-
    typo semantics (a mistyped key raises :class:`CompositionSchemaError`
    before the model call fires). Module_09 wires the narrowed
    declaration into the shipped provider adapter.
    """
    if not phase.budget_override:
        return
    if phase.function not in {"intake", "research", "plan", "edit"}:
        return
    base = budget_get(phase.function)
    apply_composition_override(base, dict(phase.budget_override))


def _append_notes(record: PhaseRecord, notes: list[str]) -> PhaseRecord:
    return PhaseRecord(
        phase_name=record.phase_name,
        function=record.function,
        duration_ms=record.duration_ms,
        outcome=record.outcome,
        notes=record.notes + tuple(notes),
    )


# ---------------------------------------------------------------------------
# Reproduce phase
# ---------------------------------------------------------------------------


_REPRODUCE_TIMEOUT_SECONDS: int = 120


def _run_reproduce_phase(
    phase: PhaseSpec,
    work_order: WorkOrder,
    repo_root: Path,
    *,
    spec_name: str,
    phase_records: list[PhaseRecord],
    sink: EventSink,
    reproduce_command: str | None,
) -> None:
    """Run the reproduce phase; raise :class:`UnconfirmedBugError` on refusal.

    The reproduce command source cascade:

    1. Explicit ``reproduce_command`` argument to :func:`run_playbook`.
    2. Phase's own ``reproduce_command`` field.
    3. Derived from :attr:`WorkOrder.success_criteria` treated as
       pytest node ids.

    A non-zero exit confirms reproduction (the failing test failed as
    reported). A zero exit or a missing source raises.
    """
    emit_budget_declared(
        sink,
        {
            "function": phase.function,
            "phase": phase.name,
            "playbook": spec_name,
            "source": "composition",
        },
    )
    start = time.monotonic()
    command = reproduce_command or phase.reproduce_command
    if command is None:
        command = _reproduce_command_from_success_criteria(work_order)
    if command is None:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        phase_records.append(
            PhaseRecord(
                phase_name=phase.name,
                function=phase.function,
                duration_ms=elapsed_ms,
                outcome="raised",
                notes=("reproduce: no command available",),
            )
        )
        raise UnconfirmedBugError(
            "bug_fix reproduce phase has no runnable command; "
            "supply reproduce_command or a WorkOrder.success_criteria pytest node id",
            function="reproduce",
            payload={"playbook": spec_name},
        )
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=_REPRODUCE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        phase_records.append(
            PhaseRecord(
                phase_name=phase.name,
                function=phase.function,
                duration_ms=elapsed_ms,
                outcome="raised",
                notes=(f"reproduce: command failed to launch: {exc}",),
            )
        )
        raise UnconfirmedBugError(
            f"reproduce command failed to launch: {exc}",
            function="reproduce",
            payload={"playbook": spec_name, "command": command},
        ) from exc
    elapsed_ms = int((time.monotonic() - start) * 1000)
    if completed.returncode == 0:
        phase_records.append(
            PhaseRecord(
                phase_name=phase.name,
                function=phase.function,
                duration_ms=elapsed_ms,
                outcome="raised",
                notes=("reproduce: command exited zero: bug did not reproduce",),
            )
        )
        raise UnconfirmedBugError(
            f"reproduce command exited 0; bug did not reproduce under {command!r}",
            function="reproduce",
            payload={
                "playbook": spec_name,
                "command": command,
                "returncode": completed.returncode,
                "stdout_tail": (completed.stdout or "")[-500:],
                "stderr_tail": (completed.stderr or "")[-500:],
            },
        )
    phase_records.append(
        PhaseRecord(
            phase_name=phase.name,
            function=phase.function,
            duration_ms=elapsed_ms,
            outcome="ok",
            notes=(
                f"reproduce: confirmed failure (returncode={completed.returncode})",
            ),
        )
    )


def _reproduce_command_from_success_criteria(
    work_order: WorkOrder,
) -> str | None:
    """Return a pytest command derived from success_criteria, or ``None``.

    Every criterion that looks like a pytest node id (contains ``::``
    or ends in ``.py``) becomes a positional argument. If none match
    the heuristic, returns ``None`` so the caller raises
    :class:`UnconfirmedBugError`.
    """
    node_ids = [
        crit
        for crit in work_order.success_criteria
        if "::" in crit or crit.endswith(".py")
    ]
    if not node_ids:
        return None
    joined = " ".join(node_ids)
    return f"pytest {joined}"


# ---------------------------------------------------------------------------
# Edit dispatch
# ---------------------------------------------------------------------------


def _run_edit_single(
    spec: PlaybookSpec,
    phase: PhaseSpec,
    change_plan: ChangePlan,
    indexes: IndexBundle,
    provider: MemoryFunctionProvider,
    *,
    sink: EventSink,
    phase_records: list[PhaseRecord],
) -> CandidateDiff:
    """Run a single edit call. Wraps :class:`BoundedContextError` for extract."""
    emit_budget_declared(
        sink,
        {
            "function": phase.function,
            "phase": phase.name,
            "playbook": spec.name,
            "source": "composition",
        },
    )
    _apply_phase_budget_override(phase)
    start = time.monotonic()
    try:
        candidate = edit_fn(change_plan, indexes, provider, sink=sink)
    except MemoryFunctionError as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        phase_records.append(
            PhaseRecord(
                phase_name=phase.name,
                function=phase.function,
                duration_ms=elapsed_ms,
                outcome="raised",
            )
        )
        if spec.name == "refactor_extract" and _is_bounded_context(exc):
            target_names = [t.symbol.name for t in change_plan.target_symbols]
            raise OversizeTargetError(
                f"refactor_extract target(s) exceed edit budget: {target_names!r}. "
                f"Reduce the target function before extraction is attempted.",
                function="edit",
                payload={
                    "playbook": spec.name,
                    "target_symbols": target_names,
                    "original_error": str(exc),
                },
            ) from exc
        raise
    elapsed_ms = int((time.monotonic() - start) * 1000)
    phase_records.append(
        PhaseRecord(
            phase_name=phase.name,
            function=phase.function,
            duration_ms=elapsed_ms,
            outcome="ok",
        )
    )
    return candidate


def _run_edit_loop(
    spec: PlaybookSpec,
    phase: PhaseSpec,
    change_plan: ChangePlan,
    indexes: IndexBundle,
    provider: MemoryFunctionProvider,
    *,
    sink: EventSink,
    phase_records: list[PhaseRecord],
) -> list[CandidateDiff]:
    """Iterate over load_manifest files, one edit per group.

    The plan's ``iteration_bound`` is the hard cap; a manifest that
    would exceed it raises :class:`IterationBoundExceededError`
    before the first model call.
    """
    files = _group_manifest_by_file(change_plan.load_manifest)
    max_from_phase = phase.max_iterations or change_plan.iteration_bound
    max_iters = min(max_from_phase, change_plan.iteration_bound)
    if len(files) > max_iters:
        raise IterationBoundExceededError(
            f"edit_loop over {len(files)} files exceeds iteration_bound "
            f"{max_iters} (plan={change_plan.iteration_bound}, "
            f"phase={phase.max_iterations})",
            function="edit",
            payload={
                "playbook": spec.name,
                "file_count": len(files),
                "iteration_bound": max_iters,
            },
        )
    edits: list[CandidateDiff] = []
    for i, (file_path, refs) in enumerate(files):
        emit_budget_declared(
            sink,
            {
                "function": phase.function,
                "phase": phase.name,
                "playbook": spec.name,
                "iteration": i,
                "file_path": file_path,
                "source": "composition",
            },
        )
        _apply_phase_budget_override(phase)
        # Per-iteration budget override is a documented narrowing.
        # The apply_composition_override call above already exercised
        # the composition layer; this one adds the per-iteration cap
        # if it differs from the phase's static override.
        if phase.per_iteration_budget is not None:
            base = budget_get("edit")
            apply_composition_override(
                base, {"input_target": phase.per_iteration_budget}
            )
        # Build a per-file sub-plan by narrowing load_manifest +
        # target_symbols to entries touching this file.
        sub_targets = tuple(
            t for t in change_plan.target_symbols if t.symbol.file_path == file_path
        )
        sub_manifest = tuple(refs)
        sub_plan = ChangePlan(
            target_symbols=sub_targets or change_plan.target_symbols,
            load_manifest=sub_manifest,
            invariants=change_plan.invariants,
            verification_criteria=change_plan.verification_criteria,
            risk_assessment=change_plan.risk_assessment,
            iteration_bound=change_plan.iteration_bound,
            metadata=change_plan.metadata,
        )
        start = time.monotonic()
        try:
            candidate = edit_fn(sub_plan, indexes, provider, sink=sink)
        except MemoryFunctionError:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            phase_records.append(
                PhaseRecord(
                    phase_name=phase.name,
                    function=phase.function,
                    duration_ms=elapsed_ms,
                    outcome="raised",
                    notes=(f"iteration {i} on {file_path}",),
                )
            )
            raise
        elapsed_ms = int((time.monotonic() - start) * 1000)
        phase_records.append(
            PhaseRecord(
                phase_name=phase.name,
                function=phase.function,
                duration_ms=elapsed_ms,
                outcome="ok",
                notes=(f"iteration {i} on {file_path}",),
            )
        )
        edits.append(candidate)
    return edits


def _group_manifest_by_file(
    manifest: tuple[SymbolRef, ...],
) -> list[tuple[str, list[SymbolRef]]]:
    """Return the manifest grouped by ``file_path`` in stable order."""
    order: list[str] = []
    grouped: dict[str, list[SymbolRef]] = {}
    for ref in manifest:
        key = ref.file_path or "(unspecified)"
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(ref)
    return [(fp, grouped[fp]) for fp in order]


def _is_bounded_context(exc: MemoryFunctionError) -> bool:
    """Return True when ``exc`` is the edit-side BoundedContextError."""
    return type(exc).__name__ == "BoundedContextError"


__all__ = [
    "IterationBoundExceededError",
    "OversizeTargetError",
    "PhaseRecord",
    "PhaseSpec",
    "PlaybookResult",
    "PlaybookSchemaError",
    "PlaybookSpec",
    "UnconfirmedBugError",
    "UnknownPlaybookError",
    "parse_playbook_payload",
    "run_playbook",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
