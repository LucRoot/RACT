"""Process-group spawn + tree-kill primitives for SubstrateLoop rollback.

External reviewer REVIEW_4_UNKNOWN §B3 flagged that the current rollback
path sends ``SIGKILL`` to a single process; grandchildren spawned by the
step keep running past the transaction boundary and can hold worktree
file handles open, blocking cleanup and (worse) surviving as orphaned
daemons past the rollback that was supposed to guarantee "the tree
returns to the pre-step state."

This module wraps ``subprocess.Popen`` so every child launched under
SubstrateLoop is its own process-group leader (POSIX) or dedicated Job
Object (Windows) and provides a single ``kill_tree`` primitive that
reaps parent + every descendant. Two backends:

- **POSIX**: ``os.setsid()`` via ``start_new_session=True`` gives the
  child a fresh session + process group whose ID equals the child's
  PID. ``os.killpg(pgid, SIGKILL)`` reaps every descendant that stayed
  in the group.
- **Windows**: ``CREATE_NEW_PROCESS_GROUP`` + a per-process Job Object
  (kernel-level bag). Killing the Job Object is atomic across the
  entire tree; ``taskkill /F /T /PID <pid>`` is the CLI-shaped
  fallback we ship when the Job Object is not available (test env or
  minimal python install).

The module is import-clean on both POSIX and Windows -- platform-only
imports live behind runtime checks and try/except so mypy + ruff can
lint on either OS without a spurious ``ModuleNotFoundError``.

Design rationale: reviewer §B3 / §C4 / §E2 all agree that the fix must
be structural (spawn-time flag + kill-time primitive) rather than a
"try to remember to reap children" convention. The primitive lives in
one module so every substrate call site uses the same reaper.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


_LOG = logging.getLogger(__name__)


_IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProcessGroupError(RuntimeError):
    """Raised when process-group spawn or reaping fails structurally.

    Distinct from a step's own non-zero exit -- this only fires when the
    substrate cannot enforce the group boundary itself (e.g. Windows
    ``CreateJobObject`` refused).
    """


# ---------------------------------------------------------------------------
# Handle
# ---------------------------------------------------------------------------


@dataclass
class ProcessGroupHandle:
    """Handle to one spawned process + its whole descendant tree.

    ``popen`` is the top-level ``subprocess.Popen``.
    ``pgid`` is the POSIX process-group id (== popen.pid on POSIX);
    ``None`` on Windows.
    ``job_handle`` is the Windows Job Object handle (opaque; ``None`` on
    POSIX). We keep the raw handle so ``kill_tree`` can call
    ``TerminateJobObject`` at reap time.
    ``argv`` is the command as spawned; kept for logging.
    ``spawned_at`` is a monotonic timestamp for reap-latency tests.
    """

    popen: subprocess.Popen[bytes]
    pgid: int | None = None
    job_handle: Any | None = None
    argv: tuple[str, ...] = ()
    spawned_at: float = field(default_factory=time.monotonic)

    @property
    def pid(self) -> int:
        return self.popen.pid

    def is_running(self) -> bool:
        """True while ``popen`` (the parent) has not exited.

        Reflects the parent only -- descendants may keep running past
        the parent's exit; use ``kill_tree`` to sweep them.
        """
        return self.popen.poll() is None


# ---------------------------------------------------------------------------
# Spawn
# ---------------------------------------------------------------------------


def spawn(
    argv: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | str | None = None,
    stdin: int | None = subprocess.DEVNULL,
    stdout: int | None = subprocess.PIPE,
    stderr: int | None = subprocess.PIPE,
) -> ProcessGroupHandle:
    """Spawn ``argv`` as a fresh process-group leader.

    - POSIX: sets ``start_new_session=True`` so ``os.setsid`` runs in
      the child before ``exec``; the child's PID becomes its process
      group id, giving us a single killpg target for the whole tree.
    - Windows: adds ``CREATE_NEW_PROCESS_GROUP`` + attempts to create
      a Job Object and assign the child to it. If the Job Object
      creation fails (rare -- Python's ``pywin32`` not present),
      ``kill_tree`` falls back to ``taskkill /F /T /PID``.

    ``env=None`` inherits the parent env; sandbox call sites should
    pre-compute a scrubbed env via ``ract.security.sandbox_env`` and
    pass it in. ``stdin`` defaults to DEVNULL so the child cannot
    silently block on stdin from a headless run.

    Returns a ``ProcessGroupHandle`` -- callers hold it for the
    lifetime of the step, then call ``kill_tree(handle)`` on rollback.
    """
    argv_tuple = tuple(str(a) for a in argv)
    cwd_str = str(cwd) if cwd is not None else None

    if _IS_WINDOWS:
        # SP Q2 amendment (OpenRouter DEFECT verdict): between
        # ``subprocess.Popen`` return and ``AssignProcessToJobObject``
        # the child was executing untracked -- a grandchild spawned in
        # that window escaped the Job Object bag. Fix: pass
        # CREATE_SUSPENDED so the primary thread does not run until
        # the Job Object is assigned; resume the thread after.
        creationflags = 0
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
        popen = subprocess.Popen(
            argv_tuple,
            env=env,
            cwd=cwd_str,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )
        job_handle = _try_create_job_object(popen.pid)
        # Resume the primary thread now that the process is (or has
        # attempted to be) bound to the Job Object. Best-effort:
        # a resume failure still leaves the process suspended, which
        # is loud in Task Manager -- preferable to a silent race.
        _resume_thread(popen)
        return ProcessGroupHandle(
            popen=popen,
            pgid=None,
            job_handle=job_handle,
            argv=argv_tuple,
        )

    # POSIX path.
    popen = subprocess.Popen(
        argv_tuple,
        env=env,
        cwd=cwd_str,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
    # After start_new_session, the child called setsid() so its PGID
    # equals its PID.
    return ProcessGroupHandle(
        popen=popen,
        pgid=popen.pid,
        job_handle=None,
        argv=argv_tuple,
    )


# ---------------------------------------------------------------------------
# Windows Job Object helper
# ---------------------------------------------------------------------------


def _resume_thread(popen: subprocess.Popen[bytes]) -> None:
    """Resume a Windows process spawned with CREATE_SUSPENDED.

    ``popen._handle`` on Windows is the process handle; the primary
    thread's handle is not exposed via subprocess. We use
    ``OpenThread`` + ``ResumeThread`` on the first thread of the PID.
    Best-effort; a failure here leaves the process suspended (loud in
    Task Manager) rather than racing to spawn grandchildren outside
    the Job Object.
    """
    if not _IS_WINDOWS:
        return
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Snapshot the process' threads and resume the first one.
        # CreateToolhelp32Snapshot(dwFlags=0x00000004 /* THREADS */,
        # th32ProcessID=0).
        TH32CS_SNAPTHREAD = 0x00000004
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
        if snapshot in (-1, 0, None):
            return

        class _THREADENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_ulong),
                ("cntUsage", ctypes.c_ulong),
                ("th32ThreadID", ctypes.c_ulong),
                ("th32OwnerProcessID", ctypes.c_ulong),
                ("tpBasePri", ctypes.c_long),
                ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", ctypes.c_ulong),
            ]

        entry = _THREADENTRY32()
        entry.dwSize = ctypes.sizeof(_THREADENTRY32)

        thread_first = kernel32.Thread32First
        thread_first.argtypes = [ctypes.c_void_p, ctypes.POINTER(_THREADENTRY32)]
        thread_first.restype = ctypes.c_int
        thread_next = kernel32.Thread32Next
        thread_next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_THREADENTRY32)]
        thread_next.restype = ctypes.c_int
        open_thread = kernel32.OpenThread
        open_thread.restype = ctypes.c_void_p
        open_thread.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        resume = kernel32.ResumeThread
        resume.argtypes = [ctypes.c_void_p]
        resume.restype = ctypes.c_ulong
        close_handle = kernel32.CloseHandle

        THREAD_SUSPEND_RESUME = 0x0002
        pid = popen.pid
        ok = thread_first(snapshot, ctypes.byref(entry))
        while ok:
            if entry.th32OwnerProcessID == pid:
                thandle = open_thread(THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if thandle:
                    resume(thandle)
                    close_handle(thandle)
                    break
            ok = thread_next(snapshot, ctypes.byref(entry))
        close_handle(snapshot)
    except Exception:  # noqa: BLE001 -- best-effort resume
        pass


def _try_create_job_object(pid: int) -> Any | None:
    """Attempt to create a Windows Job Object and assign ``pid``.

    Returns the raw handle on success; ``None`` on any failure
    (missing ``ctypes`` primitive, ``AssignProcessToJobObject``
    refused, non-Windows caller). The caller falls back to
    ``taskkill /F /T`` when this returns ``None``.

    Kept small on purpose -- the Job Object API is only invoked here
    and in ``kill_tree``; we deliberately do not maintain a persistent
    job hierarchy across the substrate. Each spawn gets its own bag.
    """
    if not _IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes  # noqa: F401 -- ensures import validity

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # CreateJobObjectW(lpJobAttributes, lpName) -> HANDLE
        create_job = kernel32.CreateJobObjectW
        create_job.restype = ctypes.c_void_p
        job = create_job(None, None)
        if not job:
            return None

        # Set JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE so when the harness
        # exits, every process in the bag is reaped by the kernel --
        # defence in depth for the case where the caller forgets to
        # kill_tree explicitly.
        _set_kill_on_job_close(kernel32, job)

        PROCESS_ALL_ACCESS = 0x1F0FFF
        open_process = kernel32.OpenProcess
        open_process.restype = ctypes.c_void_p
        open_process.argtypes = [
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        proc = open_process(PROCESS_ALL_ACCESS, False, pid)
        if not proc:
            return None

        assign = kernel32.AssignProcessToJobObject
        assign.restype = ctypes.c_int
        assign.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        ok = assign(job, proc)
        kernel32.CloseHandle(proc)
        if not ok:
            return None
        return job
    except OSError:
        return None
    except Exception:  # noqa: BLE001 -- fallback path is fine
        return None


def _set_kill_on_job_close(kernel32: Any, job: Any) -> None:
    """Set JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE on ``job``.

    Best-effort -- a failure here is not fatal; ``TerminateJobObject``
    at reap time still works.
    """
    try:
        import ctypes

        # struct JOBOBJECT_BASIC_LIMIT_INFORMATION -- we only touch
        # LimitFlags. Layout matches Windows headers.
        class _BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_ulong),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_ulong),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_ulong),
                ("SchedulingClass", ctypes.c_ulong),
            ]

        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class _EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BASIC_LIMIT),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        JobObjectExtendedLimitInformation = 9

        info = _EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        kernel32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
    except Exception:  # noqa: BLE001 -- best-effort
        pass


# ---------------------------------------------------------------------------
# Kill tree
# ---------------------------------------------------------------------------


def kill_tree(
    handle: ProcessGroupHandle,
    *,
    grace_period_seconds: float = 0.0,
    close_handle: bool = True,
) -> None:
    """SIGKILL the parent + every descendant spawned under ``handle``.

    - POSIX: ``os.killpg(handle.pgid, SIGKILL)`` reaps every process
      that stayed in the group (``start_new_session=True`` at spawn
      guarantees the group).
    - Windows: ``TerminateJobObject`` on the assigned Job Object reaps
      atomically across the tree. When the Job Object could not be
      created at spawn, falls back to ``taskkill /F /T /PID`` which
      walks the process tree by PID.

    ``grace_period_seconds`` optionally sends the platform's soft
    terminate signal (SIGTERM / CTRL_BREAK_EVENT) first and waits up
    to that many seconds before escalating. Default 0.0 = immediate
    hard kill (the rollback path wants absolute environmental
    sanitisation per §B3, not polite shutdown).

    ``close_handle=True`` releases the Job Object handle after
    terminate; tests may set False to inspect the handle post-reap.

    Idempotent: reaping an already-dead tree is a no-op.
    """
    # Nothing to do if the parent is already reaped and no descendants
    # can plausibly remain (best-effort -- we still try killpg / job
    # terminate on POSIX because grandchildren can outlive the parent).
    if _IS_WINDOWS:
        _kill_tree_windows(handle, close_handle=close_handle)
        return

    _kill_tree_posix(handle, grace_period_seconds=grace_period_seconds)


def _kill_tree_posix(
    handle: ProcessGroupHandle, *, grace_period_seconds: float
) -> None:
    """POSIX process-group reap."""
    import signal

    pgid = handle.pgid
    if pgid is None:
        # Spawned without start_new_session (defensive) -- fall back
        # to killing the parent only. This never fires from
        # SubstrateLoop's own spawn path; only exercised when a
        # caller wraps a foreign Popen.
        if handle.popen.poll() is None:
            handle.popen.kill()
        _wait_reap(handle.popen)
        return

    try:
        if grace_period_seconds > 0.0:
            try:
                os.killpg(pgid, signal.SIGTERM)  # type: ignore[attr-defined]
            except (ProcessLookupError, PermissionError):
                # Group already gone or unreachable -- proceed to
                # SIGKILL sweep anyway.
                pass
            deadline = time.monotonic() + grace_period_seconds
            while time.monotonic() < deadline:
                if handle.popen.poll() is not None:
                    break
                time.sleep(0.05)

        try:
            os.killpg(pgid, signal.SIGKILL)  # type: ignore[attr-defined]
        except (ProcessLookupError, PermissionError):
            # Nothing left to reap.
            pass
    finally:
        _wait_reap(handle.popen)


def _kill_tree_windows(
    handle: ProcessGroupHandle, *, close_handle: bool
) -> None:
    """Windows Job Object reap with taskkill fallback."""
    if handle.job_handle is not None:
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # TerminateJobObject(hJob, uExitCode) -> BOOL
            terminate = kernel32.TerminateJobObject
            terminate.restype = ctypes.c_int
            terminate.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            terminate(handle.job_handle, 1)
            if close_handle:
                kernel32.CloseHandle(handle.job_handle)
                handle.job_handle = None
        except OSError:
            _taskkill_tree(handle.pid)
        except Exception:  # noqa: BLE001
            _taskkill_tree(handle.pid)
    else:
        _taskkill_tree(handle.pid)
    _wait_reap(handle.popen)


def _taskkill_tree(pid: int) -> None:
    """Fallback -- ``taskkill /F /T /PID`` walks the child tree."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        # We never raise on kill failure -- a dead tree we could not
        # confirm is still preferable to holding a step transaction
        # open. Log and move on.
        _LOG.warning("taskkill fallback failed for pid=%s: %s", pid, exc)


def _wait_reap(popen: subprocess.Popen[bytes]) -> None:
    """Best-effort wait so the OS releases the parent's PID slot."""
    try:
        popen.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _LOG.warning(
            "process %s did not exit within 5s of tree kill; leaked zombie possible",
            popen.pid,
        )
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "ProcessGroupError",
    "ProcessGroupHandle",
    "kill_tree",
    "spawn",
]


# RACT 0.5.1
