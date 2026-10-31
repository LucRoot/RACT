"""Run one interactive turn and report it as session events.

LR:: The interactive session used to hand an intent to the one-shot CLI
dispatcher, which printed as it went: nothing for seconds on a slow model,
raw provider errors with no next step, and no way to say what changed. A
turn now goes through ``run_ract`` directly and every visible thing is a
session event (docs/EVENTS_SESSION.md, version 2): ``turn.started``, the
plan with its assumption and confidence, each step's start and end, a
heartbeat while silent, streamed text on the channel it belongs to,
``agent.retry`` when the provider is retried, ``error.surfaced`` with a hint
and the workspace state, and ``turn.finished`` with the verdict and the
verification and provenance facts the harness measured.

The function runs on whatever thread calls it; the session calls it on a
worker thread so Ctrl-C stays responsive (see ``ract.turn_context``).
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ract import (
    config_errors,
    egress_ledger,
    plan_gate,
    turn_context,
    turn_summary,
    undo_backup,
)
from ract.executor.worktree import working_tree_status
from ract.session_events import EventStream, Heartbeat, TextWriter, plan_event_data
from ract.verification import VerificationRecord


@dataclass(frozen=True)
class TurnRequest:
    """What the session asks a turn to do."""

    config: Path
    intent: str
    session_id: str | None
    resume: bool
    dry_run: bool = False
    mode: str = "default"
    auto: bool = False
    # Skip the planner: the intent is one answer step that writes nothing
    # (B-042, `/ask` and `ract -p --ask`).
    ask: bool = False
    # The session's write lock, shared by every turn (turn_context.persisting).
    write_lock: Any = None
    # `default` mode with no terminal to ask (`ract -p` without
    # `--accept-edits`): a step that changes a file is refused (B-034).
    refuse_changes: bool = False
    # A per-run token budget from --token-budget; None uses token_budget in ract.yaml (B-065).
    token_budget: int | None = None
    # Package 3 (B-033s): returns the operator lines typed during the turn that are not yet sent.
    queued: Any = None
    # G-216 W1: the session's grant pin (ADR-0048 D3); None pins at the first load.
    grant_pin: str | None = None
    # G-216 W4: the operator is at a terminal (a session, not --yolo or headless),
    # so a tier-3 command can ask even when file edits are auto-accepted.
    terminal: bool = False
    # B-113: the session's tier-3 mode and its session approvals.
    tier3_mode: str = "ask"
    tier3_session_approvals: Any = None


def _on_disk_name(root: Path, name: str) -> str:
    """``name`` as the file system spells it (H5); see ``workspace_path.on_disk_name``."""
    from ract.workspace_path import on_disk_name

    return on_disk_name(root, name)


def provenance_notice(unsigned: list[str]) -> str:
    """The unsigned-files notice in the words an operator reads (standard 12).

    The project term and the release status are left to docs/PROVENANCE.md; the
    terminal names the files and the place that explains them.
    """
    return (
        f"provenance: {len(unsigned)} file(s) have no signature yet "
        f"({', '.join(unsigned)}). See docs/PROVENANCE.md."
    )


# (pattern on the error text, hint). First match wins. Every hint names the
# next action or the exact command.
_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        # B-110 D5: the step agent loop ended without writing the step's file.
        re.compile(r"ended without changing", re.I),
        "the model ended the step without writing its file; ask again naming the "
        "file and the change, or set agent.step_tools to false in ract.yaml",
    ),
    (
        # B-110 D5: the step agent loop used its token budget.
        re.compile(r"tokens, more than its \d+", re.I),
        "raise agent.max_tokens_per_step in ract.yaml, or split the step",
    ),
    (
        # Package 4 (H1): Windows refuses a path of 260 characters or more.
        re.compile(r"Windows refuses paths of \d+ characters or more", re.I),
        "use a shorter folder or file name, then run the intent again",
    ),
    (
        # Only a refused connection: a step refused by RACT itself ("refused
        # to replace", a path refusal) is not a provider problem (S-026).
        re.compile(
            r"connection refused|actively refused|unreachable|Request failed"
            r"|ConnectError|timed out",
            re.I,
        ),
        "start your model server, or fix the provider url in ract.yaml; "
        "`ract doctor --check-providers` checks it",
    ),
    (
        re.compile(r"produced no content|returned an empty answer", re.I),
        "the model sent an empty reply for that step; run it again, or set a "
        "stronger model for this provider in ract.yaml",
    ),
    (
        # S2 (B-074 FOUND): api_key names an environment variable that is unset.
        re.compile(r"is not set in this environment; nothing was sent", re.I),
        "set the variable the message names, or remove api_key from that provider's "
        "block in ract.yaml if the server needs no key",
    ),
    (
        # B-095 (S2 D1): a reply cut off at the output limit, twice.
        re.compile(r"was cut off twice", re.I),
        "raise max_tokens for this provider in ract.yaml, or ask for a smaller change",
    ),
    (
        # B-095 (S2 D2): a new file that does not parse.
        re.compile(r"refused to create .*not valid python", re.I),
        "the model's file has a syntax error; run the request again, or ask for a "
        "smaller change",
    ),
    (
        # B-096 (S2 D3): the reply is labelled as another file.
        re.compile(r"label of another file", re.I),
        "run the request again, or name one file per step",
    ),
    (
        # B-103 (S2 D11): the operator cancelled the plan; not a setup problem.
        re.compile(r"Plan cancelled: nothing was run", re.I),
        "you cancelled the plan; run the intent again when you want it, or "
        "change the request",
    ),
    (
        # B-102 (S2 D10): a written file imports a name its module lacks.
        re.compile(r"imports a name that does not exist", re.I),
        "the file imports a name its module does not define; run the request again, "
        "or name the module and the name in the intent",
    ),
    (
        # B-083 (cold reader row 7): the novelty budget, not the provider.
        re.compile(r"Novelty budget exhausted", re.I),
        "this run's budget for new files is used up: pass --allow-novelty-overrun, "
        "raise novelty_budget in ract.yaml, or ask for a smaller change",
    ),
    (
        re.compile(r"refused to replace", re.I),
        "use /ask (or `ract -p --ask`) for an answer that writes no file, or say "
        "in the intent which change you want",
    ),
    (
        re.compile(r"has no terminal to ask", re.I),
        "pass --accept-edits to let this run change files, or --ask for an answer "
        "that writes nothing",
    ),
    (
        # B-097 (S2 D9): an approval the user said no to is not a setup problem.
        re.compile(r"Approval denied for step", re.I),
        "you did not approve that step, so nothing after it ran; run the intent "
        "again and approve it, or change the request",
    ),
    (
        # A repository-supplied command or model host in an untrusted run
        # (S-025, S-030): the next action is a trust decision, not the intent.
        re.compile(r"repository is not trusted", re.I),
        "run `ract trust` here if you chose what ract.yaml names, or change ract.yaml",
    ),
    (
        re.compile(r"\brefused\b", re.I),
        "nothing was written for that step; change the intent as the error says",
    ),
    (
        re.compile(r"HTTP 401|HTTP 403|\bapi[_ ]key\b|unauthori", re.I),
        "check the API key variable named in ract.yaml for this provider",
    ),
    (
        re.compile(r"HTTP 429", re.I),
        "the provider is still rate limiting; wait a minute, lower the request rate "
        "in the rate_limit block of ract.yaml, or switch provider",
    ),
    (
        re.compile(r"finish_reason=length|output limit", re.I),
        "raise or remove `max_tokens` for this provider in ract.yaml",
    ),
    (
        re.compile(r"Configuration file not found", re.I),
        "run `ract setup` here to create one",
    ),
    (
        re.compile(r"Could not parse JSON plan|did not contain a usable", re.I),
        "the model's reply was not a plan; try again, or use a model that follows "
        "JSON instructions (set it in ract.yaml)",
    ),
    (
        re.compile(r"Interrupted", re.I),
        "run the intent again when you are ready",
    ),
    (
        # Windows file names (package T). Each hint names the file action the user can take.
        re.compile(r"is a Windows device name", re.I),
        "choose a different file name: CON, NUL, AUX, COM1 and LPT1 are reserved by Windows",
    ),
    (
        re.compile(r"ends in a dot or space", re.I),
        "remove the trailing dot or space from the file name, then run the intent again",
    ),
    (
        re.compile(r"could not change it|left these paths as they are", re.I),
        "the file is read-only or open in another program: make it writable "
        "(attrib -R <file>) or close the program using it, then run the intent again",
    ),
    (
        re.compile(r"untracked, so git has no copy", re.I),
        "git does not track this file yet: commit it (git add, then git commit) and run "
        "the intent again, or apply the saved patch yourself",
    ),
    (
        re.compile(r"could not snapshot the working tree", re.I),
        "a file in the project could not be read, perhaps because another program has it "
        "open: close it and run the intent again",
    ),
    (
        # The duplication guard refused a write that repeats existing code (package R). The
        # hint says what the user can ask for; the message and the guard are the harness's.
        re.compile(r"Duplication guard blocked write", re.I),
        "the change repeats code that already exists in the project; ask for something "
        "new, or name the existing code you want reused",
    ),
    (
        # The model answered with no steps (D3). The provider is reachable, so the
        # provider check does not apply; the next action is a rephrase or a model.
        re.compile(r"Plan contains no steps|did not return a plan", re.I),
        "the model returned no steps for this intent; rephrase it with the file and "
        "the change you want, or pick another model with /model",
    ),
)
_DEFAULT_HINT = "run `ract doctor --check-providers` to check the setup, then try again"

# Process exit codes for a failed turn (docs/EVENTS_SESSION.md, "Exit
# codes"), checked in order: a connection refused is "provider unavailable",
# not "refused by policy".
_EXIT_CODES: tuple[tuple[re.Pattern[str], int], ...] = (
    # A run that used its token_budget (B-065): exit 4, a budget was exhausted.
    (re.compile(r"stopped: this run used", re.I), 4),
    (
        re.compile(
            r"actively refused|unreachable|Request failed|ConnectError|timed out"
            r"|HTTP 5\d\d|HTTP 429",
            re.I,
        ),
        6,
    ),
    # B-194: the configuration problems, from the table the providers word
    # them with (config_errors), so "api_key ..." is exit 2 as "api key" was.
    *((pattern, 2) for pattern in config_errors.PATTERNS),
    (
        re.compile(r"\brefused\b|not written: path refused|Preflight validation", re.I),
        3,
    ),
)


def exit_code_for(error: str) -> int:
    """The exit code of a turn that failed with ``error`` (1 when unclassified)."""
    for pattern, code in _EXIT_CODES:
        if pattern.search(error):
            return code
    return 1


def hint_for(error: str) -> str:
    for pattern, hint in _HINTS:
        if pattern.search(error):
            return hint
    return _DEFAULT_HINT


def _changed(
    before: dict[str, str] | None, after: dict[str, str] | None
) -> list[str] | None:
    if before is None or after is None:
        return None
    paths = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    return sorted(p for p in paths if not p.startswith(".ract/"))


def _tests_without_project_code(project: Path, changed: list[str]) -> list[str]:
    """The changed test files that import no project module and start no process (B-120)."""
    from ract.import_check import is_test_file, uses_project_code

    found: list[str] = []
    for name in changed:
        if not is_test_file(name):
            continue
        target = project / name
        try:
            if target.is_symlink() or not target.is_file():
                continue
            text = target.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"[session_turn] {name} not read for B-120: {exc}", flush=True)
            continue
        if uses_project_code(project, name, text) is False:
            found.append(name)
    return found


def _workspace_line(changed: list[str] | None) -> str:
    if changed is None:
        return "file changes are not tracked here (not a git repository)"
    if not changed:
        return "no files were changed"
    n = len(changed)
    return (
        f"{n} file{'s' if n != 1 else ''} changed: {', '.join(changed[:10])}"
        + (f" and {n - 10} more" if n > 10 else "")
        + " (unstaged; review with git diff)"
    )


def _provenance(
    unsigned: list[str], changed: list[str] | None, project: Path
) -> dict[str, Any]:
    """S-015b: signed only when every changed file's knot verifies (G-226 note 1).

    A file with no knot is unsigned; a file whose knot is present and does
    not verify (``ract provenance verify``'s own check, offline) is named in
    ``unverified_files``, and the turn is not signed.
    """
    from ract.provenance_cli import NO_ROOTKNOT_PREFIX, verify_artifact

    unverified: list[str] = []
    for name in changed or []:
        if name in unsigned:
            continue
        path = project / name
        if not path.is_file():
            continue
        try:
            ok, message = verify_artifact(path, project)
        except Exception as exc:  # noqa: BLE001 - a check that fails is not a pass
            print(f"[provenance] {name} was not verified: {exc}", flush=True)
            ok, message = False, str(exc)
        if not ok and message.startswith(NO_ROOTKNOT_PREFIX):
            unsigned = [*unsigned, name]
        elif not ok:
            unverified.append(name)
    out: dict[str, Any] = {
        "signed": bool(changed) and not unsigned and not unverified,
        "unsigned_files": list(unsigned),
    }
    if unverified:
        out["unverified_files"] = unverified
    # D-143: each signed file's record sits beside it; the operator commits it
    # with the file to keep the record (the summary names them).
    out["sidecars"] = [
        _sidecar_name(name)
        for name in changed or []
        if name not in unsigned
        and name not in unverified
        and (project / _sidecar_name(name)).is_file()
    ]
    return out


def _sidecar_name(name: str) -> str:
    head, _, base = name.rpartition("/")
    return f"{head}/.{base}.rootknot.json" if head else f".{base}.rootknot.json"


class _TurnReporter:
    """Receives events from deep in the run and keeps the text channel right.

    While a step runs, model deltas are the content of that step's file, so
    they go on the ``artifact`` channel under its path; outside a step they
    are an answer.
    """

    def __init__(self, stream: EventStream, turn: int, cancel: threading.Event) -> None:
        self._stream = stream
        self._turn = turn
        self._cancel = cancel
        self._lock = threading.Lock()
        self._writer: TextWriter | None = None
        self.plan_reported = False
        self.streamed = False
        # B-061c: each ``review.finished`` of the turn, for ``turn.finished.review``.
        self.reviews: list[dict[str, Any]] = []

    def __call__(self, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            if kind in {"step.started", "step.finished"}:
                self._close_writer()
            if kind == "plan.proposed":
                self.plan_reported = True
            if kind == "review.finished":
                self.reviews.append(data)
            self._stream.emit(kind, data, turn=self._turn)
            if kind == "step.started" and data.get("target"):
                self._writer = self._stream.writer(
                    turn=self._turn, channel="artifact", path=str(data["target"])
                )

    def delta(self, text: str) -> None:
        if self._cancel.is_set() or not text:
            return
        with self._lock:
            if self._writer is None:
                self._writer = self._stream.writer(turn=self._turn)
            self.streamed = True
            self._writer.feed(text)

    def _close_writer(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def close(self) -> None:
        with self._lock:
            self._close_writer()


def run_turn(
    stream: EventStream,
    request: TurnRequest,
    *,
    turn: int,
    cancel: threading.Event,
    queued: bool = False,
) -> int:
    """Run one turn. Returns a process exit code: 0 done, 5 interrupted, or the
    code for the failure (``exit_code_for``: 1 failed, 2 configuration,
    3 refused, 6 provider unavailable)."""
    from ract.ract_runner import run_ract  # noqa: PLC0415 -- heavy import, interactive path only

    reporter = _TurnReporter(stream, turn, cancel)
    written: list[str] = []
    # B-023: every command the harness runs in this turn, for the verifier.
    step_runs: list[Any] = []
    turn_context.bind(
        cancel,
        reporter,
        written=written,
        runs=step_runs,
        write_lock=request.write_lock,
        queued=request.queued,
    )
    # V7-08: the egress ledger attributes this turn's requests to it.
    egress_ledger.set_run(f"{stream.session}:{turn}")
    started = time.monotonic()
    project = Path(request.config).resolve().parent
    stream.emit("turn.started", {"input": request.intent, "queued": queued}, turn=turn)
    # The before/after comparison is only a cross-check (G-026), so the
    # "before" status runs beside planning instead of in front of it: it
    # cost about 0.18 s of every turn's time to first request (B-036).
    before_box: dict[str, dict[str, str] | None] = {}
    before_thread = threading.Thread(
        target=lambda: before_box.update(state=working_tree_status(project)),
        name="ract-status-before",
        daemon=True,
    )
    before_thread.start()

    backup_box: list[undo_backup.TurnBackup] = []
    try:
        with (
            undo_backup.turn(project, request=request.intent) as backup,
            egress_ledger.collecting(),
            egress_ledger.watching_connections() as connections,
            Heartbeat(
                stream,
                turn=turn,
                waiting_on="model",
                cancel=cancel,
                connecting=lambda: connections["connecting"],
            ),
        ):
            backup_box.append(backup)
            result: Any = run_ract(
                request.config,
                request.intent,
                token_budget=request.token_budget,
                dry_run=request.dry_run,
                mode=request.mode,
                session_id=request.session_id,
                resume=request.resume,
                auto=request.auto,
                refuse_changes=request.refuse_changes,
                ask=request.ask,
                stream=True,
                stream_callback=reporter.delta,
                grant_pin=request.grant_pin,
                terminal=request.terminal,
                tier3_mode=request.tier3_mode,
                tier3_session_approvals=request.tier3_session_approvals,
            )
    except Exception as exc:  # noqa: BLE001 -- the session must survive; detail goes to the hint
        result = None
        error_text = f"{type(exc).__name__}: {exc}"
    else:
        error_text = result.error if result is not None and not result.is_ok() else ""
        if request.refuse_changes and error_text.startswith("Approval denied"):
            error_text = (
                "refused: `default` mode asks before changing a file, and this run "
                f"has no terminal to ask ({error_text})"
            )
    finally:
        reporter.close()
        # B-192: unbinding resets the count, so it is read first.
        turn_changes = turn_context.changes_made()
        turn_context.bind(None)

    # What RACT wrote is the answer; the before/after comparison is only a
    # cross-check, reported when it disagrees (G-026).
    before_thread.join()
    observed = _changed(before_box.get("state"), working_tree_status(project))
    # S-015b: a Rootknot sidecar (.name.rootknot.json) is RACT's record of a
    # file, not a file the turn changed for the user.
    changed: list[str] | None = sorted(
        _on_disk_name(project, name)
        for name in written
        if not (
            Path(name).name.startswith(".")
            and Path(name).name.endswith(".rootknot.json")
        )
    )
    if observed is None and not written:
        changed = None  # not a git repository and nothing written: unknown
    duration = int((time.monotonic() - started) * 1000)
    workspace = _workspace_line(changed)
    if backup_box and backup_box[0].saved:
        workspace += f"; {backup_box[0].describe()}"
    others = sorted(set(observed or []) - set(written))
    if others and not cancel.is_set():
        stream.emit(
            "notice",
            {
                "level": "warning",
                "text": "files changed during the turn that RACT did not write: "
                + ", ".join(others[:10])
                + (f" and {len(others) - 10} more" if len(others) > 10 else ""),
            },
            turn=turn,
        )

    if cancel.is_set():
        # The session has already reported the interrupt; say nothing more.
        return 5

    # B-038: facts for the summary, observed by RACT, not reported by the model.
    turn_backup = backup_box[0] if backup_box else None
    stats = (
        turn_summary.diffstat(
            project,
            changed,
            turn_backup.folder if turn_backup is not None else None,
            set(turn_backup.saved) if turn_backup is not None else set(),
        )
        if changed
        else {}
    )
    undo_folder = (
        f"{backup_box[0].folder.as_posix()}/"
        if backup_box and backup_box[0].changed
        else None
    )
    # The backup's name, for undo_backup.previous_version: a renderer never
    # has to take a path apart from an event (L-141 decision 3).
    backup_id = backup_box[0].turn_id if backup_box and backup_box[0].changed else None

    def finished(
        outcome: str,
        verdict: str,
        unsigned: list[str],
        claims: list[str] | None = None,
        answer: str | None = None,
        runs: list[Any] | None = None,
        not_run_reason: str = "",
        seen: list[int] | None = None,
    ) -> None:
        # The VERIFIER is harness code (ADR-0049 D4): only the runs the
        # harness made count, and a run by the scripted runner never does.
        # B-192: the changes and the runs are replayed in the order they
        # happened, so a write after a passing run makes it stale.
        record = verification_record(runs or [], seen, turn_changes)
        fake = [r for r in runs or [] if r.runner == "fake"]
        verification = record.result(claims or []).to_event()
        if fake:
            verification["fake_runs"] = len(fake)
        if verification.get("status") == "not-run" and turn_summary.names_a_test(
            request.intent
        ):
            # B-121, now with B-112's reason: the request named a test and no
            # real run backs the turn. Present only then.
            verification["test_named"] = True
            verification["not_run_reason"] = not_run_reason or (
                "the scripted runner answered; no command ran"
                if fake
                else "no test ran"
            )
        # B-120: a new or rewritten test file that never touches project code.
        no_project_code = _tests_without_project_code(project, changed or [])
        if no_project_code:
            verification["no_project_code"] = no_project_code
        stream.emit(
            "turn.finished",
            {
                "outcome": outcome,
                "duration_ms": duration,
                "verdict": verdict,
                "workspace": workspace,
                "changed": changed,
                "diffstat": stats,
                "undo": undo_folder,
                "backup_id": backup_id,
                "checkpoint": None,
                "verification": verification,
                # B-090 (H5): the unsigned list names files as the disk spells them.
                "provenance": _provenance(
                    [_on_disk_name(project, name) for name in unsigned],
                    changed,
                    project,
                ),
                "citations": None if answer is None else _citations(project, answer),
                "review": list(reporter.reviews) or None,
            },
            turn=turn,
        )

    if error_text.startswith(plan_gate.CANCELLED):
        # The operator cancelled the plan (ADR-0049 D12): nothing ran, which
        # is the outcome they chose, so the turn is refused with exit 0.
        stream.emit("notice", {"level": "info", "text": error_text}, turn=turn)
        finished("refused", "You cancelled the plan; nothing was run.", [])
        return 0

    if error_text:
        stream.error(
            _first_sentences(error_text),
            hint=hint_for(error_text),
            workspace=workspace,
            turn=turn,
        )
        if error_text.startswith("stopped: this run used"):
            # A token budget stop (B-065): its own outcome, exit 4.
            finished("budget", "Stopped: the run used its token budget.", [])
        else:
            finished("failed", "The turn failed.", [])
        return exit_code_for(error_text)

    value = result.unwrap()
    unsigned: list[str] = []
    runs: list[Any] = []
    seen: list[int] = []
    failed: list[Any] = []
    not_run_reason = ""
    if request.dry_run or not hasattr(value, "step_results"):
        if not reporter.plan_reported:
            stream.emit("plan.proposed", plan_event_data(value), turn=turn)
        verdict = "Planned only; nothing was run."
    else:
        if not reporter.streamed:
            for step_result in value.step_results:
                target = step_result.step.expected_artifact
                content = step_result.content
                if not content.endswith("\n"):
                    content += "\n"
                if target:
                    stream.text(content, turn=turn, channel="artifact", path=target)
                else:
                    stream.text(content, turn=turn)
        unsigned = list(getattr(value, "unsigned_artifacts", []))
        n = len(value.step_results)
        verdict = f"Done: {n} step{'s' if n != 1 else ''} ran; no tests were run."
        if turn_summary.names_a_test(request.intent):
            # J4 (B-112): the named test runs, under the grant, asked first.
            from ract.approval_callback import console_tier_3_prompt
            from ract.policy.verify import run_named_tests

            # G-216 W4: whoever answers the turn's steps, or the operator at
            # the terminal in auto-accept; --yolo and headless have no one.
            asks = request.auto or request.terminal
            runs, not_run_reason = run_named_tests(
                project,
                request.intent,
                cast(Any, console_tier_3_prompt) if asks else None,
                expected_pin=request.grant_pin,
                mode=request.tier3_mode,
                session_approvals=request.tier3_session_approvals,
            )
            real = [r for r in runs if r.runner != "fake"]
            if real:
                passed = all(r.passed for r in real)
                verdict = (
                    f"Done: {n} step{'s' if n != 1 else ''} ran; the named test "
                    + ("passed." if passed else "failed.")
                )
        # B-023 (ADR-0049 D4): what the steps ran counts too; a failed real
        # run keeps the turn from done, and the verdict names it.
        after_steps = turn_changes
        kinds = [(kind, result) for kind, result, _seen in step_runs]
        seen = [changes for _kind, _result, changes in step_runs]
        kinds += [("tests", r) for r in runs]
        seen += [after_steps] * len(runs)
        runs = [result for _kind, result in kinds]
        failed = [
            (kind, result)
            for kind, result in kinds
            if result.runner != "fake" and not result.passed
        ]
        if failed:
            kind, first = failed[0]
            more = f" and {len(failed) - 1} more" if len(failed) > 1 else ""
            verdict = (
                f"Not done: {n} step{'s' if n != 1 else ''} ran; the {kind} run "
                f"`{' '.join(first.argv)}` failed (exit {first.exit_code}){more}."
            )
    if unsigned:
        stream.emit(
            "notice",
            {"level": "warning", "text": provenance_notice(unsigned)},
            turn=turn,
        )
    # A reply that says tests pass, in a turn where RACT ran none (R-113).
    answer = "\n".join(
        sr.content
        for sr in getattr(value, "step_results", [])
        if not sr.step.expected_artifact and sr.step.tool_call is None
    )
    finished(
        "failed" if failed else "done",
        verdict,
        unsigned,
        turn_summary.unverified_claims(answer),
        answer,
        runs=runs,
        not_run_reason=not_run_reason,
        seen=seen,
    )
    return 1 if failed else 0


def verification_record(
    runs: list[Any], seen: list[int] | None, total: int
) -> VerificationRecord:
    """The turn's VerificationRecord, its changes and runs replayed in order (B-192).

    LR:: The record was built after the turn from the runs alone, and no
    change was ever noted, so a passing run followed by a later write still
    read ``verified``. ``seen[i]`` is how many writes came before run ``i``;
    ``total`` is the turn's writes in all. A run by the scripted runner
    never counts (G-215). A test run that found no tests (pytest's exit 5,
    "no tests ran") is no check: with no other run the turn is ``no-tests``.
    """
    record = VerificationRecord()
    for i, run in enumerate(runs):
        before = seen[i] if seen is not None and i < len(seen) else None
        while before is not None and record.changes < before:
            record.note_change()
        if run.runner != "fake" and _found_no_tests(run):
            record.tests_found = False
        elif run.runner != "fake":
            code = run.exit_code if run.exit_code is not None else -1
            record.record(
                run.argv, code if run.killed_by is None else -1, run.duration_ms
            )
    while record.changes < total:
        record.note_change()
    return record


def _found_no_tests(run: Any) -> bool:
    """True for a pytest run that collected nothing (exit 5, "no tests ran")."""
    stdout = getattr(run, "stdout", "") or ""
    return run.exit_code == 5 and "no tests ran" in stdout


# At most this many citation items travel in one event; the counts cover all.
_CITATION_ITEMS = 60


def _citations(root: Path, answer: str) -> dict[str, Any]:
    """The answer's file and line citations, checked against the repository (B-037b).

    LR:: The model's word that something is at a file and line is checked by
    the harness (B-037a verifier) before the summary shows it: verified,
    unverified with the reason, or not checked (a protected or outside path,
    too many). Paths and reasons are made printable here.
    """
    from ract import citations as cite
    from ract.session_events import safe_text

    results = cite.verify(root, cite.extract(answer))
    counts = {"verified": 0, "unverified": 0, "not_checked": 0}
    items: list[dict[str, Any]] = []
    for result in results:
        key = "not_checked" if result.status == "not checked" else result.status
        counts[key] = counts.get(key, 0) + 1
        c = result.citation
        if len(items) < _CITATION_ITEMS:
            items.append(
                {
                    "path": safe_text(c.path),
                    "lines": str(c.start) if c.start == c.end else f"{c.start}-{c.end}",
                    "status": result.status,
                    "reason": safe_text(result.reason),
                }
            )
    return {**counts, "items": items}


def _first_sentences(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
