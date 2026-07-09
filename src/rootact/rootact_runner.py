# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import cast

from rootact.executor import ExecutionReport
from rootact.harness import Harness
from rootact.harness_report_enricher import enrich_harness_run
from rootact.manager import Plan, Step
from rootact.memory_arena import MemoryArena
from rootact.approval_callback import (
    console_approval_callback,
    yolo_approval_callback,
)
from rootact.preflight_validator import PreflightValidator
from rootact.project_document import ProjectDocument
from rootact.rooted import Rooted
from rootact.session_rollback import SessionRollback, SnapshotNotFoundError
from rootact.session_store import SessionCorruptedError, SessionState, SessionStore

# LR:: Supported run modes. These are intentionally simple: the harness does the
# heavy lifting; the runner just forwards the selection.
VALID_MODES = {"default", "documentation", "git"}

_ROOT_KNOT = object()


def _normalize_mode(mode: str | None) -> str:
    """Return a validated run mode or raise a clear error."""
    if mode is None:
        return "default"
    if mode not in VALID_MODES:
        raise ValueError(
            f"Unsupported run mode: {mode}. Choose from {sorted(VALID_MODES)}."
        )
    return mode


def _apply_mode_to_intent(intent: str, mode: str) -> str:
    """Rewrite *intent* based on the selected run *mode*."""
    if mode == "documentation":
        return (
            "DOCUMENTATION MODE:\n"
            "Before changing implementation, update or create the following "
            "documentation so it stays accurate and complete. "
            "Prefer README, ARCHITECTURE, AUDIT, and inline docstrings.\n\n"
            f"Original intent: {intent}"
        )
    return intent


def _session_store_for(config_path: Path) -> SessionStore:
    """Return a SessionStore rooted in the project's .rootact/sessions directory."""
    return SessionStore(config_path.parent / ".rootact" / "sessions")


def _memory_arena_for(config_path: Path, session_id: str | None) -> MemoryArena | None:
    """Return a MemoryArena for *session_id*, or None if no session is active."""
    if session_id is None:
        return None
    return MemoryArena.for_session(config_path.parent, session_id)


def _memory_arena_path(config_path: Path, session_id: str) -> Path:
    """Return the persistence path for a session's memory arena."""
    return config_path.parent / ".rootact" / "memory" / f"{session_id}.json"


def _load_project_doc(
    project_doc: Path | str | None,
) -> tuple[ProjectDocument | None, str]:
    """Load a ProjectDocument and return the doc plus a context prefix.

    Returns (None, "") if no document path is provided.
    """
    if project_doc is None:
        return None, ""
    path = Path(project_doc)
    if not path.exists():
        raise FileNotFoundError(f"Project document not found: {path}")
    doc = ProjectDocument.load(str(path))
    sections = doc.sections()
    parts: list[str] = []
    goal = sections.get("goal")
    if goal:
        parts.append(f"Project goal: {goal}")
    notes = sections.get("notes")
    if notes:
        parts.append(f"Project notes: {'; '.join(str(n) for n in notes)}")
    return doc, "\n\n".join(parts)


def _resume_intent(
    session_id: str, store: SessionStore, intent: str
) -> tuple[str, Plan | None]:
    """Load a prior session and prepend its summary to the intent.

    Returns the augmented intent and the previously stored plan (if any).
    """
    state = store.load(session_id)
    prior_intent = state.get("intent", intent)
    outcomes = state.get("outcomes", [])
    artifacts = list(state.get("artifacts", {}).keys())
    prior_plan = state.get("plan")

    summary_parts = [f"Resuming session '{session_id}'."]
    if outcomes:
        summary_parts.append(f"Prior outcomes: {', '.join(outcomes[:5])}.")
    if artifacts:
        summary_parts.append(f"Prior artifacts: {', '.join(artifacts[:5])}.")

    augmented = "\n".join(summary_parts)
    augmented += f"\n\nContinue with original intent: {prior_intent}"
    return augmented, prior_plan


def _save_session(
    session_id: str | None,
    store: SessionStore,
    intent: str,
    result: Rooted[ExecutionReport | Plan],
) -> None:
    """Persist session state after a run so it can be resumed later."""
    if session_id is None:
        return

    plan: Plan | None = None
    outcomes: list[str] = []
    artifacts: dict[str, object] = {}

    if result.is_ok() and result.value is not None:
        value = result.value
        if isinstance(value, ExecutionReport):
            outcomes = [
                f"{sr.step.action} -> {sr.step.expected_artifact}"
                for sr in value.step_results
            ]
            artifacts = dict(value.artifacts)
        elif isinstance(value, Plan):
            plan = value

    state = SessionState(
        intent=intent,
        plan=plan or Plan(assumption="no plan", confidence=0.0, steps=[]),
        artifacts=artifacts,
        outcomes=outcomes,
    )
    store.save(session_id, asdict(state))


def run_rootact(
    config_path: Path,
    intent: str,
    *,
    dry_run: bool = False,
    mode: str | None = "default",
    session_id: str | None = None,
    resume: bool = False,
    force: bool = False,
    rollback: bool = False,
    project_doc: Path | str | None = None,
    yolo: bool = False,
    auto: bool = False,
    reload: bool = False,
    stream: bool = False,
    stream_callback: Callable[[str], None] | None = None,
    allow_load_bearing_override: bool = False,
    allow_novelty_overrun: bool = False,
) -> Rooted[ExecutionReport | Plan]:
    """
    Run a complete RootAct cycle for *intent* using the configuration at *config_path*.

    If *dry_run* is True, only planning is performed and a ``Rooted[Plan]`` is
    returned. Otherwise the plan is executed and the resulting
    ``ExecutionReport`` is enriched with a diff summary before being returned.

    Supported *mode* values: "default", "documentation", "git".

    If *session_id* is provided, the run state is persisted under
    ``.rootact/sessions/{session_id}.json`` so it can be resumed with
    ``resume=True``. When resuming, the stored intent and a summary of prior
    work are prepended to the prompt.

    If *session_id* already exists and *resume* is False, the run is blocked
    unless *force* is True. This prevents accidental overwrites of prior work.

    If *rollback* is True, the pre-execution snapshot for *session_id* is
    restored and no planning or execution occurs. *rollback* requires
    *session_id*.

    If *project_doc* is provided, the document's goal and notes are prepended
    to the intent, and the document is updated with the resulting plan after
    a successful run.

    Run-mode toggles:
    - *yolo*: execute every step without approval (default behavior).
    - *auto*: prompt for approval before each step. Non-interactive callers can
      pre-approve via an approval-decisions file; otherwise risky steps are
      blocked by the auto heuristic.
    - *reload*: execute once; if successful, immediately execute the same
      intent again so the run can observe its own changes.
    - *stream*: request a streaming completion from the provider.  The
      *stream_callback* receives each content delta; the aggregated content is
      still returned in the ExecutionReport.

    Every failure path returns a ``Rooted`` error with a clear assumption rather
    than raising.
    """
    try:
        mode = _normalize_mode(mode)
    except ValueError as exc:
        return Rooted(
            value=None,
            assumption=f"Run mode '{mode}' is supported.",
            confidence=0.0,
            provenance=["rootact_runner.run_rootact"],
            error=str(exc),
        )

    if yolo and auto:
        return Rooted(
            value=None,
            assumption="At most one of --yolo and --auto is provided.",
            confidence=0.0,
            provenance=["rootact_runner.run_rootact"],
            error="--yolo and --auto are mutually exclusive.",
        )

    config_path = Path(config_path)
    if not config_path.exists():
        return Rooted(
            value=None,
            assumption="The configuration file exists and is readable.",
            confidence=0.0,
            provenance=["rootact_runner.run_rootact"],
            error=f"Configuration file not found: {config_path}",
        )

    if resume and not session_id:
        return Rooted(
            value=None,
            assumption="A session ID is provided when resuming.",
            confidence=0.0,
            provenance=["rootact_runner.run_rootact"],
            error="--resume requires --session.",
        )

    if rollback and not session_id:
        return Rooted(
            value=None,
            assumption="A session ID is provided when rolling back.",
            confidence=0.0,
            provenance=["rootact_runner.run_rootact"],
            error="--rollback requires --session.",
        )

    store = _session_store_for(config_path)
    rollback_engine = SessionRollback(config_path.parent)

    if rollback:
        assert session_id is not None  # guarded by the rollback check above
        try:
            restored, missing = rollback_engine.restore(session_id)
        except SnapshotNotFoundError as exc:
            return Rooted(
                value=None,
                assumption=f"A snapshot exists for session '{session_id}'.",
                confidence=0.0,
                provenance=["rootact_runner.run_rootact"],
                error=str(exc),
            )
        report = ExecutionReport(
            intent=f"Rollback session '{session_id}'",
            step_results=[],
            assumptions=[
                "Pre-execution snapshot was captured before the last run.",
                f"Restored {len(restored)} file(s); {len(missing)} missing.",
            ],
            provenance={"restored": restored, "missing": missing},
            artifacts={},
        )
        return Rooted(
            value=report,
            assumption="Rollback restored files from the pre-execution snapshot.",
            confidence=1.0 if not missing else 0.8,
            provenance=["rootact_runner.run_rootact"],
        )
    if session_id and not resume and store.exists(session_id) and not force:
        return Rooted(
            value=None,
            assumption="An existing session is only overwritten when explicitly forced.",
            confidence=0.0,
            provenance=["rootact_runner.run_rootact"],
            error=(
                f"Session '{session_id}' already exists. "
                "Use --resume to continue it or --force to overwrite."
            ),
        )

    preflight = PreflightValidator(config_path)
    preflight_errors = preflight.validate()
    if preflight_errors:
        return Rooted(
            value=None,
            assumption="The configuration passes preflight validation.",
            confidence=0.0,
            provenance=["rootact_runner.run_rootact"],
            error=f"Preflight validation failed: {preflight_errors}",
        )

    harness_rooted = Harness.from_config_path(
        config_path,
        allow_load_bearing_override=allow_load_bearing_override,
        allow_novelty_overrun=allow_novelty_overrun,
    )
    if not harness_rooted.is_ok():
        return cast(
            Rooted[ExecutionReport | Plan],
            harness_rooted.with_step("rootact_runner.run_rootact"),
        )

    harness: Harness = harness_rooted.unwrap()
    stored_plan: Plan | None = None

    if resume:
        assert session_id is not None  # guarded by the resume check above
        try:
            intent, stored_plan = _resume_intent(session_id, store, intent)
        except KeyError as exc:
            return Rooted(
                value=None,
                assumption=f"Session '{session_id}' exists.",
                confidence=0.0,
                provenance=["rootact_runner.run_rootact"],
                error=f"Session not found: {exc}",
            )
        except SessionCorruptedError as exc:
            return Rooted(
                value=None,
                assumption=f"Session '{session_id}' is readable and valid JSON.",
                confidence=0.0,
                provenance=["rootact_runner.run_rootact"],
                error=f"Session corrupted: {exc}",
            )

    intent = _apply_mode_to_intent(intent, mode)

    project_doc_obj: ProjectDocument | None = None
    project_doc_prefix = ""
    if project_doc is not None:
        try:
            project_doc_obj, project_doc_prefix = _load_project_doc(project_doc)
        except FileNotFoundError as exc:
            return Rooted(
                value=None,
                assumption="The project document exists and is readable.",
                confidence=0.0,
                provenance=["rootact_runner.run_rootact"],
                error=str(exc),
            )
    if project_doc_prefix:
        intent = f"{project_doc_prefix}\n\n{intent}"

    memory_arena = _memory_arena_for(config_path, session_id)

    if dry_run:
        planning_intent = intent
        if memory_arena is not None:
            memory_block = memory_arena.replay()
            if memory_block:
                planning_intent = f"{memory_block}\n\n{intent}"
        result = cast(
            Rooted[ExecutionReport | Plan],
            harness.planner.plan(planning_intent).with_step("rootact_runner.dry_run"),
        )
        if result.is_ok() and project_doc_obj is not None:
            plan = result.unwrap()
            if isinstance(plan, Plan):
                project_doc_obj._sections["plan"] = plan.steps
                project_doc_obj.save(str(project_doc))
        if memory_arena is not None:
            assert session_id is not None  # guarded by _memory_arena_for
            memory_arena.save(_memory_arena_path(config_path, session_id))
        _save_session(session_id, store, intent, result)
        return result

    approval_callback: Callable[[Step], bool] | None = None
    if auto:
        approval_callback = console_approval_callback
    elif yolo:
        approval_callback = yolo_approval_callback

    def _capture_snapshot(plan: Plan) -> None:
        if session_id is None:
            return
        artifact_paths = [
            config_path.parent / step.expected_artifact
            for step in plan.steps
            if step.expected_artifact
        ]
        rollback_engine.capture(session_id, artifact_paths)

    def _execute_once() -> Rooted[ExecutionReport | Plan]:
        return cast(
            Rooted[ExecutionReport | Plan],
            enrich_harness_run(
                harness,
                intent,
                mode=mode,
                pre_execute_callback=_capture_snapshot,
                approval_callback=approval_callback,
                memory_arena=memory_arena,
                stream=stream,
                stream_callback=stream_callback,
            ),
        )

    result = _execute_once()
    if result.is_ok() and project_doc_obj is not None:
        value = result.unwrap()
        if isinstance(value, ExecutionReport):
            project_doc_obj._sections["plan"] = [sr.step for sr in value.step_results]
        elif isinstance(value, Plan):
            project_doc_obj._sections["plan"] = value.steps
        project_doc_obj.save(str(project_doc))

    if reload and result.is_ok():
        second = _execute_once()
        if not second.is_ok():
            return second

    if memory_arena is not None:
        assert session_id is not None
        memory_arena.save(_memory_arena_path(config_path, session_id))

    _save_session(session_id, store, intent, result)
    return result


# RACT 0.1.1 - Trust and Tooling
