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


def bind(
    event: threading.Event | None,
    reporter: Reporter | None = None,
    *,
    written: list[str] | None = None,
) -> None:
    """Make ``event``, ``reporter`` and the ``written`` list the current turn.

    ``written`` collects the workspace-relative paths RACT wrote into the
    operator's files during the turn (``record_written``). None clears all
    three.
    """
    _cancel.set(event)
    _reporter.set(reporter)
    _written.set(written)


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
