"""Subagent handle protocol + subprocess-backed concrete implementation.

v0.5.1 spec-completeness module_07 (Lens 2 Delta 3). Subagents in RACT
are long-lived helper resources the loop launches to observe or
augment the primary work: a Legacy Whisperer producing a dialect
brief, a Chesterton's Fence subprocess evaluating a pre-delete gate,
a language-server child holding a semantic index, an embedding-model
sidecar. Today those helpers are constructed inline and rely on the
process teardown or explicit callers to dispose them; on a NON-T1 loop
halt (rollback / postcondition failure / commit failure / T3-T8) they
can leak past loop boundaries and hold worktree file handles,
network sockets, or GPU memory open.

The cascade primitive is orthogonal to the process-group reaper
(:meth:`SubstrateLoop._reap_active_processes`, module_05 wiring).
Process-group reap targets DIRECT subprocess trees spawned via
:meth:`SubstrateLoop.spawn_step_subprocess`; the subagent-handle
cascade targets ANY disposable resource -- Popen-backed or otherwise
-- registered via :meth:`SubstrateLoop.register_subagent_handle`.
Both cascade during a non-T1 dispose; each addresses a distinct
class of resource ownership.

Contract (Ox Alpha §2 forced-failure test gate):

- ``SubagentHandle`` protocol carries three surfaces:
  ``descriptor`` (dict for the event payload), ``is_alive()``
  (best-effort liveness probe; a stale handle returns False), and
  ``dispose(reason: str) -> bool`` (best-effort teardown; True on
  successful dispose, False on failure/no-op with the reason logged).
- ``SubprocessSubagentHandle`` wraps a :class:`subprocess.Popen` for
  the common case (subprocess-shaped subagent). ``dispose`` reaps the
  entire process tree via the module_05 :func:`process_group.kill_tree`
  primitive so a leaked grandchild is caught structurally.
- Registration order is LIFO: the most-recently-registered handle
  disposes first on cascade, mirroring the compensator-stack shape
  from ``commit_compensator.py``.

References:

- v0.2-primitive Lens 2 Delta 3 (source-doc audit
  ``_BUILD/audit_2026-08-21c/lens_2_v02_primitive_vs_kairos_wall.md``).
- Ox Alpha pipeline critique
  ``_BUILD/ract_v0.5.1_spec_completeness/ox_alpha_reviews/pipeline_challenge_2026-08-21.md``
  §2 (forced-failure integration test required).
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


_LOG = logging.getLogger(__name__)


@runtime_checkable
class SubagentHandle(Protocol):
    """Structural protocol every subagent handle satisfies.

    Concrete implementations MAY inherit or duck-type. The subprocess
    case is covered by :class:`SubprocessSubagentHandle`; a caller
    with an inline resource (e.g. a GPU-model context manager) writes a
    thin adapter satisfying this shape.
    """

    #: Free-form descriptor consumed by the ``subagent.disposed`` event
    #: payload. Recommended keys: ``kind`` (short string identifying
    #: the subagent role, e.g. ``"whisperer"`` / ``"fence"`` /
    #: ``"lsp"``), ``label`` (human-readable), and any other trace
    #: fields the operator wants surfaced in the event log. The dict
    #: is copied into the payload; do NOT mutate after registration.
    descriptor: dict[str, Any]

    def is_alive(self) -> bool:  # pragma: no cover - protocol
        """Return True while the underlying resource is still live."""
        ...

    def dispose(self, reason: str) -> bool:  # pragma: no cover - protocol
        """Best-effort teardown; return True on success, False on failure.

        ``reason`` is a short string ("cascade" / "manual" /
        "loop_dispose_unsuccessful") that lands in the trace event
        for correlation. Implementations MUST NOT raise -- a failure
        is reported by returning False and logging the specifics.
        Idempotent: a second dispose on a disposed handle is a no-op
        that returns True.
        """
        ...


@dataclass
class SubprocessSubagentHandle:
    """Subprocess-backed :class:`SubagentHandle`.

    Wraps a :class:`subprocess.Popen` and reaps the entire process
    tree via :func:`ract.executor.process_group.kill_tree` on dispose.
    Suitable for CLI-invoked subagents (Legacy Whisperer, Chesterton's
    Fence, language servers, embedding sidecars).

    Construction accepts either a live Popen (typical: the caller
    already spawned) or a :class:`ract.executor.process_group.ProcessGroupHandle`
    (typical: the caller went through
    :meth:`SubstrateLoop.spawn_step_subprocess` and got the tree-kill
    handle back). The Popen path uses ``kill_tree`` on a synthesised
    handle to guarantee the same reap semantics regardless of spawn
    surface.
    """

    popen: subprocess.Popen | None
    descriptor: dict[str, Any] = field(default_factory=dict)
    kind: str = "subprocess"
    _disposed: bool = False

    def is_alive(self) -> bool:
        if self._disposed:
            return False
        if self.popen is None:
            return False
        return self.popen.poll() is None

    def dispose(self, reason: str) -> bool:
        if self._disposed:
            # Idempotent: a second dispose on a disposed handle is a
            # no-op that returns True.
            return True
        if self.popen is None:
            self._disposed = True
            return True
        # Route through the module_05 process-group tree-killer so a
        # leaked grandchild is caught structurally (the whole reason
        # the primitive exists per Lens C C-03).
        from ract.executor.process_group import ProcessGroupHandle, kill_tree

        try:
            # Build a minimal ProcessGroupHandle around the Popen so
            # kill_tree gets the fields it needs. spawned_at is
            # best-effort; latency is a secondary telemetry axis.
            handle = ProcessGroupHandle(
                popen=self.popen,
                argv=tuple(getattr(self.popen, "args", ()) or ()),
                spawned_at=time.monotonic(),
            )
            kill_tree(handle)
            self._disposed = True
            return True
        except Exception as exc:  # noqa: BLE001 -- best-effort dispose
            _LOG.warning(
                "SubprocessSubagentHandle.dispose failed (reason=%s, kind=%s): %s",
                reason,
                self.kind,
                exc,
            )
            # Mark disposed anyway to prevent retry loops on the same
            # dead handle; the failure is logged for the operator.
            self._disposed = True
            return False


@dataclass
class InlineSubagentHandle:
    """Callable-backed :class:`SubagentHandle` for non-subprocess resources.

    Adapter for the case where the subagent is an in-process resource
    with its own teardown (e.g. an embedding-model context manager,
    a thread pool, an open network connection). The caller supplies
    a ``teardown`` callable that returns True on successful dispose.
    """

    teardown: Any  # Callable[[], bool] -- typed loose for duck-typing
    descriptor: dict[str, Any] = field(default_factory=dict)
    kind: str = "inline"
    _disposed: bool = False
    _liveness: Any | None = None  # Optional Callable[[], bool]

    def is_alive(self) -> bool:
        if self._disposed:
            return False
        if self._liveness is None:
            return True
        try:
            return bool(self._liveness())
        except Exception:  # noqa: BLE001 -- liveness probe never raises
            return False

    def dispose(self, reason: str) -> bool:
        if self._disposed:
            return True
        try:
            ok = bool(self.teardown())
        except Exception as exc:  # noqa: BLE001 -- best-effort dispose
            _LOG.warning(
                "InlineSubagentHandle.dispose failed (reason=%s, kind=%s): %s",
                reason,
                self.kind,
                exc,
            )
            self._disposed = True
            return False
        self._disposed = True
        return ok


def emit_subagent_disposed_event(
    handle: SubagentHandle,
    *,
    reason: str,
    ok: bool,
) -> None:
    """Emit ``subagent.disposed`` into the trace sink.

    Called from :meth:`SubstrateLoop._reap_subagent_handles` per
    dispose. Wrapped so a loop without a registered writer (unit
    tests, ad-hoc loops) still runs. Payload carries the descriptor
    dict plus the reason + outcome so an operator can grep
    ``subagent.disposed`` to correlate cascade fires to specific
    handles.
    """
    try:
        from ract.trace.sink import emit as _emit_event  # noqa: PLC0415

        descriptor = dict(getattr(handle, "descriptor", {}) or {})
        kind = str(getattr(handle, "kind", descriptor.get("kind", "unknown")))
        _emit_event(
            "subagent.disposed",  # type: ignore[arg-type]
            {
                "kind": kind,
                "descriptor": descriptor,
                "reason": str(reason),
                "ok": bool(ok),
            },
        )
    except Exception:  # noqa: BLE001 -- never fail dispose on trace error
        pass


__all__ = [
    "InlineSubagentHandle",
    "SubagentHandle",
    "SubprocessSubagentHandle",
    "emit_subagent_disposed_event",
]


# RACT 0.5.1
