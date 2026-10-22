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
from typing import Any

from ract import turn_context
from ract.executor.worktree import working_tree_status
from ract.session_events import EventStream, Heartbeat, TextWriter, plan_event_data


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


# (pattern on the error text, hint). First match wins. Every hint names the
# next action or the exact command.
_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"refused|unreachable|Request failed|ConnectError|timed out|actively refused",
            re.I,
        ),
        "start your model server, or fix the provider url in ract.yaml; "
        "`ract doctor --check-providers` checks it",
    ),
    (
        re.compile(r"HTTP 401|HTTP 403|api key|unauthori", re.I),
        "check the API key variable named in ract.yaml for this provider",
    ),
    (
        re.compile(r"HTTP 429", re.I),
        "the provider is rate limiting; wait and try again, or switch provider in ract.yaml",
    ),
    (
        re.compile(r"finish_reason=length|output limit", re.I),
        "raise or remove `max_tokens` for this provider in ract.yaml",
    ),
    (
        re.compile(r"Configuration file not found", re.I),
        "run `ract --init-provider local` here, then `ract doctor --check-providers`",
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
)
_DEFAULT_HINT = "run `ract doctor --check-providers` to check the setup, then try again"

# Until the session runs tests itself (verification.* is reserved), every
# turn says honestly that none ran.
_NOT_VERIFIED: dict[str, Any] = {"status": "not-run", "runs": []}


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


def _provenance(unsigned: list[str]) -> dict[str, Any]:
    # Signing is not wired into this release (S-015b), so no turn is signed.
    return {"signed": False, "unsigned_files": list(unsigned)}


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

    def __call__(self, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            if kind in {"step.started", "step.finished"}:
                self._close_writer()
            if kind == "plan.proposed":
                self.plan_reported = True
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
    """Run one turn. Returns a process-style exit code (0 done, 1 failed, 5 interrupted)."""
    from ract.ract_runner import run_ract  # noqa: PLC0415 -- heavy import, interactive path only

    reporter = _TurnReporter(stream, turn, cancel)
    turn_context.bind(cancel, reporter)
    started = time.monotonic()
    project = Path(request.config).resolve().parent
    stream.emit("turn.started", {"input": request.intent, "queued": queued}, turn=turn)
    before = working_tree_status(project)

    try:
        with Heartbeat(stream, turn=turn, waiting_on="model", cancel=cancel):
            result: Any = run_ract(
                request.config,
                request.intent,
                dry_run=request.dry_run,
                mode=request.mode,
                session_id=request.session_id,
                resume=request.resume,
                auto=request.auto,
                stream=True,
                stream_callback=reporter.delta,
            )
    except Exception as exc:  # noqa: BLE001 -- the session must survive; detail goes to the hint
        result = None
        error_text = f"{type(exc).__name__}: {exc}"
    else:
        error_text = result.error if result is not None and not result.is_ok() else ""
    finally:
        reporter.close()
        turn_context.bind(None)

    changed = _changed(before, working_tree_status(project))
    duration = int((time.monotonic() - started) * 1000)

    if cancel.is_set():
        # The session has already reported the interrupt; say nothing more.
        return 5

    def finished(outcome: str, verdict: str, unsigned: list[str]) -> None:
        stream.emit(
            "turn.finished",
            {
                "outcome": outcome,
                "duration_ms": duration,
                "verdict": verdict,
                "workspace": _workspace_line(changed),
                "changed": changed,
                "checkpoint": None,
                "verification": dict(_NOT_VERIFIED),
                "provenance": _provenance(unsigned),
            },
            turn=turn,
        )

    if error_text:
        stream.error(
            _first_sentences(error_text),
            hint=hint_for(error_text),
            workspace=_workspace_line(changed),
            turn=turn,
        )
        finished("failed", "The turn failed.", [])
        return 1

    value = result.unwrap()
    unsigned: list[str] = []
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
    if unsigned:
        stream.emit(
            "notice",
            {
                "level": "warning",
                "text": f"provenance: {len(unsigned)} file(s) written without a Rootknot "
                f"({', '.join(unsigned)}). Signing is not wired into this release; "
                "see docs/PROVENANCE.md.",
            },
            turn=turn,
        )
    finished("done", verdict, unsigned)
    return 0


def _first_sentences(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
