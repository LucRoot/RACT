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
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from ract.core.module_identity import _module_knot, register_module_knot
from ract.executor.process_identity import (
    ProcessIdentity,
    capture_identity,
)

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


_IS_WINDOWS = sys.platform == "win32"


_LOG = logging.getLogger(__name__)


class SubagentHandle(Protocol):
    """Structural protocol every subagent handle satisfies.

    Concrete implementations MAY inherit or duck-type. The subprocess
    case is covered by :class:`SubprocessSubagentHandle`; a caller
    with an inline resource (e.g. a GPU-model context manager) writes a
    thin adapter satisfying this shape.

    SP amendment (Ox Alpha finding): the ``@runtime_checkable``
    decorator was removed. Runtime-checkable Protocols with data
    members (``descriptor: dict[str, Any]``) raise ``TypeError``
    on ``issubclass()`` in CPython -- and ``isinstance()`` only
    verifies method presence, missing the data attribute. The
    Protocol is now purely structural (documentation +
    static-type-checker guidance); runtime callers use duck-typed
    ``hasattr`` / ``getattr`` semantics via
    :meth:`SubstrateLoop.register_subagent_handle` which does not
    ``isinstance`` at registration time. The concrete
    :class:`SubprocessSubagentHandle` and
    :class:`InlineSubagentHandle` implementations remain the
    load-bearing surface.

    Implementations MUST:

    - Make :meth:`dispose` idempotent (a second call on a disposed
      handle returns True without doing work); the cascade
      contract in :meth:`SubstrateLoop._reap_subagent_handles`
      relies on this to survive double-cascade situations
      (run_step exception unwind followed by dispose(success=False)
      is one such path).
    - Never raise from :meth:`dispose`. The cascade catches
      exceptions defensively, but the contract is best-effort
      teardown; a raising dispose reports a failure to the
      trace log (``ok=False`` in ``subagent.disposed``).
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
    # v0.5.2 hardening module_03 (DA-A F-4 + Ox Alpha M-5): identity
    # captured at construction time so the eventual dispose can verify
    # the pid was not reused between register and cascade. ``None``
    # when the popen was ``None`` at construction or identity source
    # refused.
    _spawn_identity: ProcessIdentity | None = field(default=None, init=False)
    # v0.5.2 hardening module_03 (Ox Alpha co-build Fork 5): foreign
    # Popens (raw Popen not routed through :func:`process_group.spawn`)
    # get their pgid (POSIX) / Job Object (Windows) captured
    # retroactively at construction time. Without this, dispose
    # synthesised a bare ProcessGroupHandle at kill-time with pgid=None
    # and job_handle=None -- exactly the DA-A F-4 weak path. Now the
    # handle captures whatever the OS already had (POSIX: os.getpgid;
    # Windows: attempt AssignProcessToJobObject on the running popen)
    # so kill_tree can use the group / Job Object primitive.
    _captured_pgid: int | None = field(default=None, init=False)
    _captured_job_handle: Any | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        # Capture identity + retroactive pgid/Job Object binding at
        # construction. Best-effort; any failure degrades to bare-pid.
        if self.popen is None:
            return
        pid = self.popen.pid
        self._spawn_identity = capture_identity(pid)
        if _IS_WINDOWS:
            # Fork 5 (Windows): attempt to bind the running foreign
            # process to a fresh Job Object. Windows allows
            # AssignProcessToJobObject on a process that is not
            # already in a job (or in a job that allows nesting on
            # Win8+). If it refuses, kill_tree falls back to
            # guarded taskkill.
            from ract.executor.process_group import (  # noqa: PLC0415
                _try_create_job_object,
            )

            try:
                self._captured_job_handle = _try_create_job_object(pid)
            except Exception:  # noqa: BLE001 -- best-effort retro-bind
                self._captured_job_handle = None
            # SP amendment (cross-family Q4 QUESTION fold): when the
            # retroactive Job Object bind fails (foreign Popen was
            # already in a job that refused AssignProcessToJobObject,
            # or _try_create_job_object hit a Win7-era nested-job
            # limitation, or ctypes missing), emit a diagnostic log
            # so operators can debug why dispose falls back to
            # per-pid taskkill instead of atomic Job Object reap.
            if self._captured_job_handle is None:
                _LOG.info(
                    "SubprocessSubagentHandle: foreign Popen pid=%s "
                    "retroactive Job Object bind refused -- dispose "
                    "will fall back to guarded taskkill. Common cause: "
                    "process already in a foreign Job Object.",
                    pid,
                )
        else:
            # Fork 5 (POSIX): read the process's ACTUAL pgid from
            # the OS. When the foreign spawn used start_new_session
            # or setpgid, we capture the real group; otherwise we
            # capture the caller's group (safe -- killpg on our own
            # group would kill us, so we detect + refuse below).
            try:
                pgid = os.getpgid(pid)  # type: ignore[attr-defined]
            except (ProcessLookupError, PermissionError, OSError):
                pgid = None
            except AttributeError:  # non-POSIX fallback
                pgid = None
            # Refuse to capture our own pgid -- killpg would kill
            # RACT itself. Log + leave pgid None so dispose uses
            # bare-Popen kill.
            if pgid is not None:
                try:
                    self_pgid = os.getpgid(0)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    self_pgid = -1
                if pgid == self_pgid:
                    _LOG.warning(
                        "SubprocessSubagentHandle: foreign Popen pid=%s "
                        "shares pgid with RACT (%s); refusing pgid "
                        "capture -- kill will target parent only",
                        pid,
                        pgid,
                    )
                    pgid = None
            self._captured_pgid = pgid

    def is_alive(self) -> bool:
        if self._disposed:
            return False
        if self.popen is None:
            return False
        return self.popen.poll() is None

    def dispose(self, reason: str) -> bool:
        """Reap the subagent + every descendant. Unconditional tree-kill.

        v0.5.2 hardening module_03 (DA-A F-4 + Ox Alpha M-5):

        - No parent-exited short-circuit. The pre-hardening path
          skipped :func:`kill_tree` when ``self.popen.poll() is not
          None`` on the theory that a dead parent means no children.
          FALSE: children that fork()d then had their parent exit
          get reparented to init/system, still running under the
          original UID; on Windows the Job Object leaks the whole
          tree unless we terminate it. Tree-kill fires
          unconditionally now; the ``path`` field on the
          ``substrate.subagent.tree_kill_invoked`` event records
          which state the parent was in.
        - Identity guard. The synthesised
          :class:`ProcessGroupHandle` carries
          ``self._spawn_identity`` (captured in ``__post_init__``);
          :func:`kill_tree` re-verifies before every signal and
          refuses on PID reuse (emitting
          ``substrate.subagent.pid_reuse_detected``).
        - Foreign-Popen bind. ``self._captured_pgid`` /
          ``self._captured_job_handle`` were populated in
          ``__post_init__`` -- the synthesised handle carries them
          so :func:`kill_tree` reaches the process group / Job
          Object bag rather than falling back to per-pid taskkill.
        """
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

        # Determine dispose path for telemetry BEFORE the kill fires.
        try:
            poll_result = self.popen.poll()
        except Exception:  # noqa: BLE001 -- poll rarely raises, guard anyway
            poll_result = None
        path = "poll_exited" if poll_result is not None else "explicit"

        try:
            # Build a ProcessGroupHandle around the Popen carrying the
            # identity + retroactive pgid/Job Object binding captured
            # at construction. kill_tree uses those to reach the
            # process group / Job Object bag rather than per-pid.
            handle = ProcessGroupHandle(
                popen=self.popen,
                pgid=self._captured_pgid,
                job_handle=self._captured_job_handle,
                argv=tuple(getattr(self.popen, "args", ()) or ()),
                spawned_at=time.monotonic(),
                identity=self._spawn_identity,
            )
            _emit_tree_kill_invoked(
                handle=handle,
                path=path,
                reason=reason,
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
            _emit_tree_kill_invoked(
                handle=None,
                path="error",
                reason=reason,
                popen_pid=getattr(self.popen, "pid", None),
                identity=self._spawn_identity,
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


def _emit_tree_kill_invoked(
    *,
    handle: Any,
    path: str,
    reason: str,
    popen_pid: int | None = None,
    identity: ProcessIdentity | None = None,
) -> None:
    """Emit ``substrate.subagent.tree_kill_invoked`` unconditionally.

    Fires every time :meth:`SubprocessSubagentHandle.dispose` calls
    into :func:`kill_tree`, regardless of whether the parent Popen
    already exited. Payload carries the pid, spawn-time
    ``creation_time_ns``, the ``path`` field (``"poll_exited"`` /
    ``"explicit"`` / ``"error"``), and the caller's ``reason``.

    The ``"poll_exited"`` path is the load-bearing DA-A F-4
    telemetry: pre-hardening this path was skipped; post-hardening
    it fires and the event proves it.
    """
    try:
        from ract.trace.sink import emit as _emit_event  # noqa: PLC0415

        pid = None
        ctime = None
        if handle is not None:
            pid = getattr(handle, "pid", None)
            ident = getattr(handle, "identity", None)
            if ident is not None:
                ctime = int(ident.creation_time_ns)
        if pid is None and popen_pid is not None:
            pid = int(popen_pid)
        if ctime is None and identity is not None:
            ctime = int(identity.creation_time_ns)
        _emit_event(
            "substrate.subagent.tree_kill_invoked",  # type: ignore[arg-type]
            {
                "pid": int(pid) if pid is not None else -1,
                "creation_time_ns": int(ctime) if ctime is not None else 0,
                "path": str(path),
                "reason": str(reason),
            },
        )
    except Exception:  # noqa: BLE001 -- never fail dispose on trace error
        pass


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
    "_emit_tree_kill_invoked",
    "emit_subagent_disposed_event",
]


# RACT 0.5.1
