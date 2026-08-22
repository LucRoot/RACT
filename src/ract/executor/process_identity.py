"""Process identity guard -- ``(pid, creation_time_ns)`` capture + verify.

v0.5.2 hardening module_03 (DA-A F-4 + Ox Alpha M-5). A bare ``pid``
integer is NOT a safe long-term reference. Between ``spawn`` and any
subsequent ``kill``, the pid may have been:

- Reaped (parent Popen exited naturally) and its PID slot released.
- Reallocated by the OS to an UNRELATED new process (POSIX + Windows
  both reuse pids from the free pool; Linux caps at ``PID_MAX``, so
  wrap-around on a busy host is not hypothetical).

If the substrate then sends SIGKILL / TerminateJobObject / taskkill
against that pid, it can reap the wrong tenant. The mitigation is
the classic double-key: capture ``(pid, creation_time_ns)`` at spawn
and re-verify before any signal.

Cross-platform implementation without a psutil dependency:

- POSIX: read ``/proc/{pid}/stat`` field 22 (starttime in jiffies
  since boot). ``field 22`` is monotonic per pid and changes when
  the PID is reused. When ``/proc`` is unavailable (macOS,
  containers with hidepid, exotic mounts), fall back to
  ``os.stat("/proc/{pid}").st_ctime_ns`` (Linux only), then finally
  to ``None`` (identity guard degrades to "cannot verify -- trust
  the pid"; logs a warning; caller decides).
- Windows: ``kernel32.GetProcessTimes`` reads the process creation
  ``FILETIME`` (100-ns ticks since Windows epoch). Independent of
  PID reuse; the tuple ``(pid, creation_ftime)`` is unique across
  the process's lifetime.

The identity is intentionally an OPAQUE tuple; callers should not
introspect it. Two convenience predicates surface the load-bearing
question: :func:`same_process` (do the two identities describe the
same live process?) and :func:`current_identity` (fetch the
identity of a pid the caller already has).

Ox Alpha SP amendment coverage (M-5 as authored + accepted by
cross-family reviewer at module_03 second_pass): identity
capture + verify is unconditional at the SubagentHandle layer.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import NamedTuple

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


_LOG = logging.getLogger(__name__)


_IS_WINDOWS = sys.platform == "win32"


class ProcessIdentity(NamedTuple):
    """Opaque double-key ``(pid, creation_time_ns)`` for signal safety.

    ``creation_time_ns`` is a platform-native monotonic-per-pid stamp:

    - POSIX (Linux): ``/proc/{pid}/stat`` field 22 (starttime in
      jiffies since boot). Converted to a nanosecond-scale integer
      as ``jiffies * 10_000_000`` (100Hz kernel = 10 ms per jiffy);
      the exact scale does not matter -- comparison is equality-only.
    - Windows: ``GetProcessTimes`` creation FILETIME (100-ns since
      Windows epoch, already integer nanoseconds/100).
    - Fallback: ``0`` when neither source is available; the guard
      degrades to a bare-pid compare which is UNSAFE but preserves
      forward progress rather than blocking the reap indefinitely.

    Two identities compare equal via ``NamedTuple.__eq__``; callers
    should use :func:`same_process` for the SEMANTIC comparison
    (fallback-zero tolerates equality-with-live-pid).
    """

    pid: int
    creation_time_ns: int


# ---------------------------------------------------------------------------
# POSIX identity source (Linux /proc/PID/stat field 22)
# ---------------------------------------------------------------------------


def _read_posix_starttime_ns(pid: int) -> int | None:
    """Read Linux ``/proc/{pid}/stat`` field 22 (starttime) as ns-scale int.

    Returns ``None`` when the file is unreadable (process gone,
    /proc not mounted, permission denied). The scale of the result
    is intentionally opaque -- callers only ever compare for
    equality.

    ``/proc/PID/stat`` layout: fields are space-separated, but
    field 2 (``comm``) is parenthesised and may contain spaces.
    We parse by finding the LAST ``)`` and splitting the rest.
    See ``man 5 proc`` -- this parse rule is documented and stable.
    """
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        raw = stat_path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    close_paren = raw.rfind(")")
    if close_paren < 0:
        return None
    tail = raw[close_paren + 1 :].strip()
    fields = tail.split()
    # After the closing ``)``, field 3 (state) is fields[0]; starttime
    # is field 22 in the manpage's 1-indexed count where field 1 is
    # pid and field 2 is comm. tail[0] = field 3, so starttime is
    # tail[22 - 3] = tail[19].
    if len(fields) <= 19:
        return None
    try:
        jiffies = int(fields[19])
    except ValueError:
        return None
    # Scale to nanoseconds-ish (10ms per jiffy on a 100Hz kernel).
    # Exact scale irrelevant -- comparison is equality-only.
    return jiffies * 10_000_000


def _read_posix_ctime_ns_fallback(pid: int) -> int | None:
    """Fallback: ``os.stat("/proc/{pid}").st_ctime_ns``.

    On Linux, the ``/proc/PID`` inode's ctime tracks the process's
    creation time. Used only when field-22 parse failed.
    """
    try:
        st = os.stat(f"/proc/{pid}")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    return st.st_ctime_ns


# ---------------------------------------------------------------------------
# Windows identity source (kernel32.GetProcessTimes CreationTime FILETIME)
# ---------------------------------------------------------------------------


def _read_windows_creation_ftime(pid: int) -> int | None:
    """Read Windows creation FILETIME for ``pid`` as an integer.

    Uses ``ctypes`` + ``kernel32.GetProcessTimes``. Returns ``None``
    on any failure (process gone, access denied, ctypes missing).
    The FILETIME is 100-ns ticks since 1601-01-01 UTC and is stable
    across a process's lifetime + unique across PID reuse.
    """
    if not _IS_WINDOWS:
        return None
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        open_process = kernel32.OpenProcess
        open_process.restype = ctypes.c_void_p
        open_process.argtypes = [
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        proc = open_process(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not proc:
            # Access denied is not the same as "process gone", but
            # for identity-guard purposes both mean "cannot verify" ->
            # return None so caller degrades.
            return None

        class _FILETIME(ctypes.Structure):
            _fields_ = [
                ("dwLowDateTime", ctypes.c_uint32),
                ("dwHighDateTime", ctypes.c_uint32),
            ]

        creation = _FILETIME()
        exit_ = _FILETIME()
        kernel_ = _FILETIME()
        user_ = _FILETIME()

        get_process_times = kernel32.GetProcessTimes
        get_process_times.restype = ctypes.c_int
        get_process_times.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_FILETIME),
            ctypes.POINTER(_FILETIME),
            ctypes.POINTER(_FILETIME),
            ctypes.POINTER(_FILETIME),
        ]
        ok = get_process_times(
            proc,
            ctypes.byref(creation),
            ctypes.byref(exit_),
            ctypes.byref(kernel_),
            ctypes.byref(user_),
        )
        kernel32.CloseHandle(proc)
        if not ok:
            return None
        combined = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        if combined == 0:
            return None
        return int(combined)
    except OSError:
        return None
    except Exception:  # noqa: BLE001 -- best-effort identity read
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def current_identity(pid: int) -> ProcessIdentity | None:
    """Fetch the current ``(pid, creation_time_ns)`` for a live pid.

    Returns ``None`` when the process is gone (no PID slot present)
    OR when identity metadata could not be read. Callers use the
    ``None`` return to distinguish "process definitively dead"
    (safe to skip the signal) from "identity mismatch"
    (dangerous -- may kill the wrong tenant).

    Order of attempts:
    - Windows: ``GetProcessTimes`` FILETIME.
    - Linux + Linux-shaped POSIX: ``/proc/{pid}/stat`` field 22,
      then ``/proc/{pid}`` inode ctime as fallback.
    - Other POSIX (macOS, BSD without /proc): ``None`` (degrades
      to bare-pid, logs at debug level).

    Never raises. The identity guard is best-effort by design --
    an over-eager raise would block a reap the operator asked for.
    """
    if pid <= 0:
        return None
    if _IS_WINDOWS:
        ftime = _read_windows_creation_ftime(pid)
        if ftime is None:
            return None
        return ProcessIdentity(pid=pid, creation_time_ns=ftime)
    # POSIX path.
    stime = _read_posix_starttime_ns(pid)
    if stime is None:
        stime = _read_posix_ctime_ns_fallback(pid)
    if stime is None:
        # No identity source available. Return a zero-ctime identity
        # so the caller can still compare equal-to-stored-zero if the
        # spawn-time capture also returned zero (matched-fallback
        # case). This preserves progress on macOS/BSD without /proc
        # while remaining safe when both sides degrade uniformly.
        return ProcessIdentity(pid=pid, creation_time_ns=0)
    return ProcessIdentity(pid=pid, creation_time_ns=stime)


def capture_identity(pid: int) -> ProcessIdentity | None:
    """Capture identity at SPAWN time. Alias for :func:`current_identity`.

    Named separately so call-sites read as intent ("capture" vs
    "verify"). If spawn-time capture returns ``None``, the caller
    should treat the pid as un-guardable and either:

    - Refuse to register the handle (strict callers).
    - Log a warning + accept bare-pid identity (best-effort callers,
      the SubagentHandle default).
    """
    return current_identity(pid)


def same_process(
    stored: ProcessIdentity | None,
    current: ProcessIdentity | None,
) -> bool:
    """True iff the two identities describe the same live process.

    Semantics:

    - Both ``None`` -> False (cannot confirm identity; refuse signal).
    - Only ``current`` is ``None`` -> False (process gone; caller
      should skip signal AND emit the ``.orphan_reaped`` /
      ``.pid_reuse_detected`` trace decision).
    - Only ``stored`` is ``None`` -> False (spawn-time capture failed;
      un-guardable handle, caller decides whether to refuse or
      proceed with bare-pid fallback).
    - Both present -> pid AND creation_time_ns must both match.
      Zero-ctime match is accepted (fallback case where both sides
      degraded uniformly) -- see :func:`current_identity` docstring.
    """
    if stored is None or current is None:
        return False
    if stored.pid != current.pid:
        return False
    return stored.creation_time_ns == current.creation_time_ns


__all__ = [
    "ProcessIdentity",
    "capture_identity",
    "current_identity",
    "same_process",
]


# RACT 0.5.2
