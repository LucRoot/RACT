"""Per-turn context: the cancel signal and the event reporter.

LR:: A turn runs on a worker thread so Ctrl-C reaches the session at once
(UX baseline UX-02: Ctrl-C was ignored until the turn ended). Python cannot
stop a thread that is waiting on an HTTP response, so cancellation is
cooperative: the session sets the turn's event, and the code that changes
the workspace checks it first. An interrupted turn may still be waiting on
the model, but nothing it returns is written.

The same context carries a reporter, so code deep in the run (the planner,
the executor, the provider's retry loop) can emit session events such as
``step.started`` and ``agent.retry`` without a parameter threaded through
every call. With nothing bound, ``cancelled()`` is False and ``report()``
does nothing, so one-shot CLI runs are unchanged.

Both live in ``ContextVar``s, not thread-locals (G-026): work submitted to a
``ThreadPoolExecutor`` through ``ract.runtime.run_with_ambient`` (or any
``contextvars.copy_context().run``) sees the turn's cancel signal and
reporter, the same way it sees the ambient run id.
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

Reporter = Callable[[str, dict[str, Any]], None]

_cancel: ContextVar[threading.Event | None] = ContextVar(
    "ract_turn_cancel", default=None
)
_reporter: ContextVar[Reporter | None] = ContextVar("ract_turn_reporter", default=None)
_report_error: ContextVar[str | None] = ContextVar(
    "ract_turn_report_error", default=None
)
_written: ContextVar[list[str] | None] = ContextVar("ract_turn_written", default=None)
# B-023: the commands the harness ran in this turn, as (kind, CommandResult).
_runs: ContextVar[list[Any] | None] = ContextVar("ract_turn_runs", default=None)
_extensions_off: ContextVar[bool] = ContextVar(
    "ract_repository_extensions_off", default=False
)
_write_lock: ContextVar[Any] = ContextVar("ract_turn_write_lock", default=None)
# B-149: external text (a fetched page, a search result) put in front of the
# model since the operator last approved a proposal, as "fetched page from x".
_external: ContextVar[list[str] | None] = ContextVar("ract_turn_external", default=None)
# Package 3 (B-033s): the lines typed during the turn and not yet sent; drained at each model request.
_queued: ContextVar[Callable[[], list[str]] | None] = ContextVar(
    "ract_turn_queued", default=None
)


class CancelSignal(threading.Event):
    """A turn's cancel event that also aborts the work in flight.

    LR:: After Ctrl-C the worker thread was left blocked in the model's HTTP
    read until the reply came or the 60 s read timeout passed, and the next
    turn waited for it (G-029). Code that starts a blocking request
    registers an abort with ``on_abort`` (the provider registers closing
    its HTTP client); ``set()`` runs every registered abort, from the
    thread that cancels. On Windows a closed client ends the blocked read
    in about a millisecond.
    """

    def __init__(self) -> None:
        super().__init__()
        self._aborts_lock = threading.Lock()
        self._aborts: list[Callable[[], object]] = []

    def add_abort(self, abort: Callable[[], object]) -> None:
        with self._aborts_lock:
            self._aborts.append(abort)

    def remove_abort(self, abort: Callable[[], object]) -> None:
        with self._aborts_lock:
            if abort in self._aborts:
                self._aborts.remove(abort)

    def set(self) -> None:
        super().set()
        with self._aborts_lock:
            aborts, self._aborts = list(self._aborts), []
        for abort in aborts:
            try:
                abort()
            except Exception as exc:  # noqa: BLE001 -- one failed abort must not stop the others
                print(
                    f"[turn_context] abort failed: {exc}", file=sys.stderr, flush=True
                )


def bind(
    event: threading.Event | None,
    reporter: Reporter | None = None,
    *,
    written: list[str] | None = None,
    runs: list[Any] | None = None,
    write_lock: Any = None,
    queued: Callable[[], list[str]] | None = None,
) -> None:
    """Make the turn's cancel event, reporter, written list and write lock current.

    ``written`` collects the workspace-relative paths RACT wrote into the
    operator's files during the turn (``record_written``). ``write_lock`` is
    the session's, shared by every turn, so a write from an interrupted
    turn and a write from the next turn never interleave (``persisting``).
    None clears them all.
    """
    _cancel.set(event)
    _reporter.set(reporter)
    _written.set(written)
    _runs.set(runs)
    _write_lock.set(write_lock)
    _queued.set(queued)
    _external.set([])


def note_external(origin: str, where: str) -> None:
    """B-149: *origin* text from *where* is now in the model's context."""
    seen = _external.get()
    if seen is None:
        seen = []
        _external.set(seen)
    entry = f"{origin} from {where}"
    if entry not in seen:
        seen.append(entry)


def follows_external() -> str:
    """The approval card's origin line, or "" when no external text came first."""
    seen = _external.get() or []
    return "follows " + "; ".join(seen) if seen else ""


def approved_after_external() -> None:
    """The operator approved with the origin line shown: start counting again."""
    seen = _external.get()
    if seen is not None:
        seen.clear()


def queued_notes() -> list[str]:
    """The operator lines queued during this turn that are not yet sent (package 3).

    Each call takes them: a line goes to one model request only, and a line still
    queued when the turn ends is sent by the next turn.
    """
    source = _queued.get()
    return source() if source is not None else []


@contextmanager
def repository_extensions_off() -> Iterator[None]:
    """Load no repository-supplied extension in this block.

    LR:: A cloned repository can ship hooks (`.ract/hooks/*.json`), MCP
    servers and a skill in its `ract.yaml`. A headless run shows no trust
    prompt, and RACT has no trust store yet, so a headless run loads none of
    them (B-035, R-136); the harness reads this switch when it is built.
    """
    token = _extensions_off.set(True)
    try:
        yield
    finally:
        _extensions_off.reset(token)


def extensions_off() -> bool:
    """True when repository-supplied extensions must not be loaded."""
    return _extensions_off.get()


@contextmanager
def on_abort(abort: Callable[[], object]) -> Iterator[None]:
    """Run ``abort`` if the turn is cancelled while this block runs.

    If the turn is already cancelled, ``abort`` runs at once, so a request
    started after the cancel ends immediately too.
    """
    event = _cancel.get()
    if not isinstance(event, CancelSignal):
        yield
        return
    event.add_abort(abort)
    if event.is_set():
        event.remove_abort(abort)
        abort()
    try:
        yield
    finally:
        event.remove_abort(abort)


@contextmanager
def persisting() -> Iterator[bool]:
    """Hold the session's write lock and say whether this turn may write.

    LR:: Checking ``cancelled()`` and then writing is a race: the cancel can
    land between the two, and the next turn's write can start while this
    one is half done. Every path that persists (history, memory arena,
    project document, a step's apply, the in-place write) runs inside this
    block and writes only when it yields True. The check happens with the
    lock held, so a worker that is already writing finishes before the next
    turn's write starts, and a worker that arrives after the cancel writes
    nothing.

    >>> with turn_context.persisting() as allowed:
    ...     if allowed:
    ...         store.save(...)
    """
    lock = _write_lock.get()
    if lock is None:
        yield not cancelled()
        return
    with lock:
        yield not cancelled()


def record_written(root: Path | str, paths: Iterable[Path | str]) -> None:
    """Record files RACT wrote into the operator's working tree.

    LR:: The turn's ``changed`` list comes from the code that did the writing
    (G-026), not from comparing the tree before and after: a comparison
    misses an edit that keeps size and mtime and counts files someone else
    touched during the turn. Paths are stored relative to ``root`` with
    forward slashes.
    """
    written = _written.get()
    if written is None:
        return
    base = os.path.realpath(os.fspath(root))
    for path in paths:
        full = os.path.realpath(os.path.join(base, os.fspath(path)))
        rel = os.path.relpath(full, base).replace(os.sep, "/")
        if rel not in written:
            written.append(rel)


def record_run(kind: str, result: Any) -> None:
    """Keep a command the harness ran, for the turn's verifier (B-023)."""
    runs = _runs.get()
    if runs is not None:
        runs.append((kind, result))


@contextmanager
def recording_suspended() -> Iterator[None]:
    """Do not record writes inside this block (a step's own worktree)."""
    token = _written.set(None)
    try:
        yield
    finally:
        _written.reset(token)


def has_reporter() -> bool:
    """True when a session is listening for this context's events."""
    return _reporter.get() is not None


def cancelled() -> bool:
    """True when the current context's turn has been interrupted."""
    event = _cancel.get()
    return bool(event is not None and event.is_set())


def cancelled_within(seconds: float) -> bool:
    """True when the turn is cancelled now or within *seconds*.

    LR:: A Ctrl-C at a prompt read in the turn's worker ends that read with
    EOF a moment before the session marks the turn cancelled (the interrupt
    reaches the main thread). A prompt that reports its result at once
    reported a failure the operator never chose (adjudication row 6); waiting
    this long first lets the cancel win. A closed stdin has no cancel coming
    and only pays the wait.
    """
    event = _cancel.get()
    return bool(event is not None and event.wait(seconds))


def report(kind: str, data: dict[str, Any]) -> None:
    """Emit a session event for the current turn, if a session is listening.

    Nothing is reported once the turn is cancelled: an abandoned worker's
    late events must not appear in the next turn. A reporter that fails is
    the session's problem; the run must not stop because a progress event
    could not be shown, so the error is kept on the context and the run
    continues.
    """
    reporter = _reporter.get()
    if reporter is None or cancelled():
        return
    try:
        reporter(kind, data)
    except Exception as exc:  # noqa: BLE001 -- progress must never stop the run
        _report_error.set(f"{type(exc).__name__}: {exc}")


def last_report_error() -> str | None:
    """The last reporter failure in this context, if any."""
    return _report_error.get()


def on_retry(attempt: int, max_attempts: int, reason: str, wait_s: float) -> None:
    """``RetryPolicy`` callback: report ``agent.retry``."""
    report(
        "agent.retry",
        {
            "attempt": attempt,
            "max": max_attempts,
            "reason": reason,
            "wait_ms": int(wait_s * 1000),
        },
    )
