from __future__ import annotations


import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from ract import run_checkpoint, trust, turn_context, undo_backup
from ract.executor import ExecutionReport
from ract.harness import Harness
from ract.harness_report_enricher import enrich_harness_run
from ract.manager import Plan, Step
from ract.memory_arena import MemoryArena
from ract.approval_callback import (
    console_approval_callback,
    console_git_init_offer,
    console_proposed_reviewer,
    console_tier_2_choice,
    console_tier_3_prompt,
    review_replaces_step_question,
    console_plan_approval,
    refuse_changes_callback,
    refuse_plan_needing_approval,
    yolo_approval_callback,
)
from ract.plan_validator import PlanValidator
from ract.preflight_validator import PreflightValidator
from ract.project_document import ProjectDocument
from ract.rooted import Rooted
from ract.session_rollback import SessionRollback, SnapshotNotFoundError
from ract.session_store import SessionCorruptedError, SessionState, SessionStore

# LR:: Supported run modes. These are intentionally simple: the harness does the
# heavy lifting; the runner just forwards the selection.
VALID_MODES = {"default", "documentation", "git"}


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
    """Return a SessionStore rooted in the project's .ract/sessions directory."""
    return SessionStore(config_path.parent / ".ract" / "sessions")


def _memory_arena_for(config_path: Path, session_id: str | None) -> MemoryArena | None:
    """Return a MemoryArena for *session_id*, or None if no session is active."""
    if session_id is None:
        return None
    return MemoryArena.for_session(config_path.parent, session_id)


def _memory_arena_path(config_path: Path, session_id: str) -> Path:
    """Return the persistence path for a session's memory arena."""
    return config_path.parent / ".ract" / "memory" / f"{session_id}.json"


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


def _note(line: str) -> None:
    if turn_context.has_reporter():
        turn_context.report("notice", {"level": "info", "text": line})
    else:
        print(f"note: {line}", flush=True)


def _resume_checkpoint(
    config_path: Path, run_id: str
) -> tuple[dict[str, Any], Plan] | Rooted[ExecutionReport | Plan] | None:
    """Read run *run_id*'s checkpoint and reset its interrupted step (D13).

    Returns the checkpoint (with nothing in progress) and its plan, None
    when the run has no checkpoint, or a Rooted error when the checkpoint
    or its plan is not trusted; then nothing was run or changed.
    """
    from ract.session_events import visible_text

    root = config_path.parent
    try:
        state = run_checkpoint.load(root, run_id)
    except run_checkpoint.CheckpointRefused as exc:
        return Rooted(
            value=None,
            assumption=f"Run '{run_id}' has a checkpoint this repository's run wrote.",
            confidence=0.0,
            provenance=["ract_runner.run_ract", "run_checkpoint.load"],
            error=f"The checkpoint of run '{run_id}' is not trusted: {exc}. Nothing was run.",
        )
    if state is None:
        return None
    plan = run_checkpoint.stored_plan(state)
    validation = PlanValidator.validate(plan)
    if not validation.is_valid:
        return Rooted(
            value=None,
            assumption="The stored plan passes pre-flight validation.",
            confidence=0.0,
            provenance=["ract_runner.run_ract", "plan_validator.validate"],
            error=(
                f"The stored plan of run '{run_id}' fails validation: "
                f"{validation.message}. Nothing was run."
            ),
        )
    reset = run_checkpoint.reset_in_progress(root, state)
    for line in run_checkpoint.resume_notices(state, reset):
        _note(visible_text(line))
    for path, why in reset.left:
        _note(f"{visible_text(path)}: {why}")
    return {**state, "in_progress": None}, plan


def _approvals_for_resume(
    config_path: Path, session_id: str | None, resume: bool, plan: Plan | None
) -> frozenset[int]:
    """The steps the operator skipped in the plan being resumed (D12); none for a fresh run."""
    from ract import plan_approval_store
    from ract.approval_callback import _plan_steps
    from ract.ui.plan_approval_view import plan_hash

    if plan is None or not resume or not session_id:
        return frozenset()
    known = plan_approval_store.load(config_path.parent, session_id)
    return frozenset(known.get(plan_hash(_plan_steps(plan)), []))


def _remembering_approval(ask, config_path: Path, session_id: str | None):
    """Wrap the console plan question: an approval is remembered for the session (D12).

    The entry is keyed by the hash of the plan as it will run (edits included) and holds the
    skipped step numbers, so a resumed run takes the same skips without asking.
    """
    from ract import plan_approval_store
    from ract.approval_callback import _plan_steps
    from ract.ui.plan_approval_view import plan_hash

    def ask_and_remember(plan):
        outcome = ask(plan)
        if outcome is not None and outcome.kind == "approved" and session_id:
            shown = outcome.shown or _plan_steps(plan)
            skipped = [step.n for step in outcome.skipped]
            plan_approval_store.remember(
                config_path.parent, session_id, plan_hash(shown), skipped
            )
        return outcome

    return ask_and_remember


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
            outcomes = [sr.outcome() for sr in value.step_results]
            artifacts = dict(value.artifacts)
            # The plan that ran. It was dropped for executed runs, so the
            # report showed "no plan, confidence 0.0" for a turn that had
            # both (UX-12).
            plan = value.plan
        elif isinstance(value, Plan):
            plan = value

    state = SessionState(
        intent=intent,
        # An empty assumption marks "no plan recorded" (a failed turn); the
        # report says so instead of printing a default as data.
        plan=plan or Plan(assumption="", confidence=0.0, steps=[]),
        artifacts=artifacts,
        outcomes=outcomes,
    )
    store.save(session_id, asdict(state))


def _configured_budget(config_path: Path) -> int | None:
    """``token_budget`` from the config, or None. An unreadable config gives None;
    _run_ract reports that as it always has."""
    import yaml  # noqa: PLC0415 -- read once per run, before the cycle starts

    from ract import run_token_budget as token_budget  # noqa: PLC0415

    try:
        data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    return token_budget.parse(data.get(token_budget.FIELD))


def run_ract(
    config_path: Path, intent: str, **kwargs: Any
) -> Rooted[ExecutionReport | Plan]:
    """Run one RACT cycle inside the run's token budget (B-065).

    The budget is read from ``token_budget`` in the config. Every request the
    run makes counts against it; see ``ract.run_token_budget``.
    """
    from ract import run_token_budget as token_budget  # noqa: PLC0415

    override = kwargs.pop("token_budget", None)
    try:
        limit = (
            token_budget.parse(override)
            if override is not None
            else _configured_budget(config_path)
        )
    except token_budget.BudgetConfigError as exc:
        return Rooted(
            value=None,
            assumption="token_budget is valid.",
            confidence=0.0,
            provenance=["ract_runner.run_ract"],
            error=str(exc),
        )
    with token_budget.run_budget(limit):
        return _trusted_run(config_path, intent, **kwargs)


def _trusted_run(
    config_path: Path, intent: str, **kwargs: Any
) -> Rooted[ExecutionReport | Plan]:
    """Run a complete RACT cycle for *intent* (see ``_run_ract``).

    LR:: A repository's own commands and endpoints (hooks, MCP servers, the
    internal provider command, coverage and mutation gates, web retrieval)
    ran on every run with no question (S-025). Before anything is loaded,
    the repository's trust is decided: trusted, or nothing to trust, runs as
    before; otherwise a terminal is asked once per process, and anything
    else skips them with one line. A caller that already decided (headless
    runs, `--bare`) has turned them off and is not asked again.
    """
    root = Path(config_path).resolve().parent
    # Previous versions of the files this turn replaces (S-026). A session
    # turn binds its own and reports it in the turn summary instead.
    with undo_backup.turn(
        root, announce=lambda line: print(f"note: {line}", flush=True)
    ):
        if turn_context.extensions_off():
            return _run_ract(config_path, intent, **kwargs)
        interactive = sys.stdin.isatty() and sys.stderr.isatty()
        if trust.decide(root, interactive=interactive):
            from ract.security.sandbox_env import trusted_repository_allowlist

            with trusted_repository_allowlist(root):
                return _run_ract(config_path, intent, **kwargs)
        with turn_context.repository_extensions_off():
            return _run_ract(config_path, intent, **kwargs)


def _run_ract(
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
    refuse_changes: bool = False,
    reload: bool = False,
    stream: bool = False,
    stream_callback: Callable[[str], None] | None = None,
    allow_load_bearing_override: bool = False,
    allow_novelty_overrun: bool = False,
    ask: bool = False,
    run_id: str | None = None,
    grant_pin: str | None = None,
    terminal: bool = False,
    tier3_mode: str = "ask",
    tier3_session_approvals: Any = None,
) -> Rooted[ExecutionReport | Plan]:
    """
    Run a complete RACT cycle for *intent* using the configuration at *config_path*.

    If *dry_run* is True, only planning is performed and a ``Rooted[Plan]`` is
    returned. Otherwise the plan is executed and the resulting
    ``ExecutionReport`` is enriched with a diff summary before being returned.

    Supported *mode* values: "default", "documentation", "git".

    If *session_id* is provided, the run state is persisted under
    ``.ract/sessions/{session_id}.json`` so it can be resumed with
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

    With *run_id* the run keeps a checkpoint (ADR-0049 D13): which steps
    finished and which step is in progress. With *resume* and a checkpoint
    for that id, the step in progress is reset, finished steps are not run
    again and the stored plan runs without planning. Without a checkpoint,
    *resume* continues the session as before.

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
            provenance=["ract_runner.run_ract"],
            error=str(exc),
        )

    if yolo and auto:
        return Rooted(
            value=None,
            assumption="At most one of --yolo and --auto is provided.",
            confidence=0.0,
            provenance=["ract_runner.run_ract"],
            error="--yolo and --auto are mutually exclusive.",
        )

    config_path = Path(config_path)
    if not config_path.exists():
        return Rooted(
            value=None,
            assumption="The configuration file exists and is readable.",
            confidence=0.0,
            provenance=["ract_runner.run_ract"],
            error=f"Configuration file not found: {config_path}",
        )

    if resume and not session_id:
        return Rooted(
            value=None,
            assumption="A session ID is provided when resuming.",
            confidence=0.0,
            provenance=["ract_runner.run_ract"],
            error="--resume requires --session.",
        )

    if rollback and not session_id:
        return Rooted(
            value=None,
            assumption="A session ID is provided when rolling back.",
            confidence=0.0,
            provenance=["ract_runner.run_ract"],
            error="--rollback requires --session.",
        )

    # S-016: keep RACT's .ract/ state out of the operator's git status.
    # Local exclude only; a no-op outside a git repository.
    from ract.executor.worktree import ensure_ract_dir_excluded

    ensure_ract_dir_excluded(config_path.parent)

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
                provenance=["ract_runner.run_ract"],
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
            provenance=["ract_runner.run_ract"],
        )
    if session_id and not resume and store.exists(session_id) and not force:
        return Rooted(
            value=None,
            assumption="An existing session is only overwritten when explicitly forced.",
            confidence=0.0,
            provenance=["ract_runner.run_ract"],
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
            provenance=["ract_runner.run_ract"],
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
            harness_rooted.with_step("ract_runner.run_ract"),
        )

    harness: Harness = harness_rooted.unwrap()
    stored_plan: Plan | None = None

    checkpoint: run_checkpoint.RunCheckpoint | None = None
    resumed_plan: Plan | None = None
    if run_id is not None and not dry_run and not ask:
        try:
            undo_backup.require_name(run_id, "run id")
        except ValueError as exc:
            return Rooted(
                value=None,
                assumption="The run id is a name.",
                confidence=0.0,
                provenance=["ract_runner.run_ract"],
                error=str(exc),
            )
        resumed = _resume_checkpoint(config_path, run_id) if resume else None
        if isinstance(resumed, Rooted):
            return resumed
        state = None
        if resumed is not None:
            state, resumed_plan = resumed
            intent = state["intent"]
        checkpoint = run_checkpoint.RunCheckpoint(
            config_path.parent, run_id, intent, state=state
        )

    if resume and resumed_plan is None:
        assert session_id is not None  # guarded by the resume check above
        try:
            intent, stored_plan = _resume_intent(session_id, store, intent)
        except KeyError as exc:
            return Rooted(
                value=None,
                assumption=f"Session '{session_id}' exists.",
                confidence=0.0,
                provenance=["ract_runner.run_ract"],
                error=f"Session not found: {exc}",
            )
        except SessionCorruptedError as exc:
            return Rooted(
                value=None,
                assumption=f"Session '{session_id}' is readable and valid JSON.",
                confidence=0.0,
                provenance=["ract_runner.run_ract"],
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
                provenance=["ract_runner.run_ract"],
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
            harness.planner.plan(planning_intent).with_step("ract_runner.dry_run"),
        )
        with turn_context.persisting() as allowed:
            if not allowed:
                return result  # an interrupted turn leaves no history (see below)
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
    # Plan approval (ADR-0049 D12): `default` mode asks once for a plan of two
    # or more steps that changes a file; with nobody to ask, it is refused.
    plan_approval: Callable[[Plan], Any] | None = None
    if refuse_changes:
        # `default` mode with nobody to ask (B-034): answers only.
        approval_callback = refuse_changes_callback
        plan_approval = refuse_plan_needing_approval
    elif auto:
        approval_callback = console_approval_callback
        plan_approval = console_plan_approval
        # Someone is at the terminal: a tier-2 tool call asks them (B-110 D6).
        # --yolo and headless runs leave it unset, so a tier-2 call is refused.
        from ract.tier2_approvals import SessionApprovals

        harness.executor.tier_2_approver = SessionApprovals(
            config_path.parent, session_id, console_tier_2_choice
        )
        # A tier-3 command asks the operator at the terminal (ADR-0048 D6);
        # --yolo and headless runs leave it unset, so tier 3 never runs there.
        harness.executor.tier_3_approver = console_tier_3_prompt
        harness.git_init_offer = console_git_init_offer
        if harness.executor.step_tools is not None:
            # Proposed -> reviewed -> applied: each hunk is asked about before
            # it reaches the files, which replaces the per-step question.
            harness.executor.proposed_reviewer = console_proposed_reviewer
            approval_callback = review_replaces_step_question(approval_callback)
    elif yolo:
        approval_callback = yolo_approval_callback
    executor = getattr(harness, "executor", None)
    if executor is not None:
        if terminal and not yolo and executor.tier_3_approver is None:
            # G-216 W4: auto-accept in a session at a terminal accepts file
            # edits without asking; a tier-3 command still asks the operator.
            executor.tier_3_approver = console_tier_3_prompt
        # G-216 W1: the session's pin; every step's tier-3 context compares with it.
        executor.grant_pin = grant_pin
        executor.tier3_mode = tier3_mode
        executor.tier3_session_approvals = tier3_session_approvals
    if plan_approval is console_plan_approval:
        plan_approval = _remembering_approval(plan_approval, config_path, session_id)

    def _capture_snapshot(plan: Plan) -> None:
        if session_id is None:
            return
        artifact_paths = [
            config_path.parent / step.expected_artifact
            for step in plan.steps
            if step.expected_artifact
        ]
        rollback_engine.capture(session_id, artifact_paths)

    def _execute_once(plan: Plan | None = None) -> Rooted[ExecutionReport | Plan]:
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
                ask=ask,
                plan_override=plan,
                plan_approval=plan_approval,
                skipped_steps=_approvals_for_resume(
                    config_path, session_id, resume, plan
                ),
            ),
        )

    if checkpoint is None:
        result = _execute_once()
    else:
        with run_checkpoint.recording(checkpoint):
            result = _execute_once(resumed_plan)
        if result.is_ok():
            checkpoint.complete()
    # LR:: An interrupted turn's worker can still be waiting on the model
    # when the prompt is back; when the reply finally arrives, nothing from
    # it may be kept. Without this the late worker saved the interrupted
    # intent into the session history, the memory arena and the project
    # document (G-027). The check runs under the session's write lock, so
    # it cannot race the next turn's write (G-029).
    with turn_context.persisting() as allowed:
        if not allowed:
            return result
        if result.is_ok() and project_doc_obj is not None:
            value = result.unwrap()
            if isinstance(value, ExecutionReport):
                project_doc_obj._sections["plan"] = [
                    sr.step for sr in value.step_results
                ]
            elif isinstance(value, Plan):
                project_doc_obj._sections["plan"] = value.steps
            project_doc_obj.save(str(project_doc))

    if reload and result.is_ok():
        second = _execute_once()
        if not second.is_ok():
            return second

    with turn_context.persisting() as allowed:
        if not allowed:
            return result
        if memory_arena is not None:
            assert session_id is not None
            memory_arena.save(_memory_arena_path(config_path, session_id))
        _save_session(session_id, store, intent, result)
    return result


# RACT 0.1.1 - Trust and tooling
