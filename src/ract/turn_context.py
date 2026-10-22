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
every call. Both are bound per thread; with nothing bound, ``cancelled()``
is False and ``report()`` does nothing, so one-shot CLI runs are unchanged.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

Reporter = Callable[[str, dict[str, Any]], None]

_local = threading.local()


def bind(event: threading.Event | None, reporter: Reporter | None = None) -> None:
    """Make ``event`` and ``reporter`` this thread's turn context (None clears)."""
    _local.event = event
    _local.reporter = reporter


def cancelled() -> bool:
    """True when the current thread's turn has been interrupted."""
    event = getattr(_local, "event", None)
    return bool(event is not None and event.is_set())


def report(kind: str, data: dict[str, Any]) -> None:
    """Emit a session event for the current turn, if a session is listening.

    A reporter that fails is the session's problem; the run must not stop
    because a progress event could not be shown, so the error is recorded
    on the context and the run continues.
    """
    reporter = getattr(_local, "reporter", None)
    if reporter is None or cancelled():
        return
    try:
        reporter(kind, data)
    except Exception as exc:  # noqa: BLE001 -- progress must never stop the run
        _local.report_error = f"{type(exc).__name__}: {exc}"


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
