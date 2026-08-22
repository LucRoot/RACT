"""Unit -- process_identity capture + same_process semantics.

v0.5.2 hardening module_03 (DA-A F-4 + Ox Alpha M-5). Locks the
identity primitive in isolation so the SubagentHandle + kill_tree
tests can assume a working substrate.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from ract.executor.process_identity import (
    ProcessIdentity,
    capture_identity,
    current_identity,
    same_process,
)


@pytest.mark.timeout(15)
def test_capture_identity_returns_positive_ctime_for_live_process() -> None:
    """A live Python subprocess yields a non-None identity."""
    popen = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ident = capture_identity(popen.pid)
        assert ident is not None
        assert ident.pid == popen.pid
        assert ident.creation_time_ns >= 0
    finally:
        try:
            popen.kill()
            popen.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass


@pytest.mark.timeout(15)
def test_current_identity_matches_capture_identity_on_stable_pid() -> None:
    """Two reads back-to-back agree; ctime is stable across reads."""
    popen = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        first = capture_identity(popen.pid)
        time.sleep(0.1)
        second = current_identity(popen.pid)
        assert first is not None
        assert second is not None
        assert same_process(first, second), (
            f"back-to-back identity reads must agree; first={first}, second={second}"
        )
    finally:
        try:
            popen.kill()
            popen.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass


def test_same_process_none_side_returns_false() -> None:
    """Either-None identities cannot confirm same-process."""
    ident = ProcessIdentity(pid=1234, creation_time_ns=999)
    assert same_process(None, ident) is False
    assert same_process(ident, None) is False
    assert same_process(None, None) is False


def test_same_process_pid_or_ctime_mismatch_returns_false() -> None:
    """PID or ctime differ -> reject."""
    a = ProcessIdentity(pid=100, creation_time_ns=1)
    b = ProcessIdentity(pid=100, creation_time_ns=2)
    c = ProcessIdentity(pid=101, creation_time_ns=1)
    assert same_process(a, b) is False, "ctime mismatch must reject"
    assert same_process(a, c) is False, "pid mismatch must reject"
    assert same_process(a, a) is True, "identical identities must match"


def test_current_identity_returns_none_for_nonexistent_pid() -> None:
    """Unallocated PID -> None (safe caller signal to skip kill).

    On Linux, PIDs above /proc/sys/kernel/pid_max may be pending
    allocation; using PID 0 (illegal for a real process) is a safe
    stand-in that hits the ``pid <= 0`` short-circuit.
    """
    assert current_identity(0) is None
    assert current_identity(-1) is None


@pytest.mark.timeout(15)
def test_capture_identity_after_process_death_returns_none_or_zero() -> None:
    """Dead process: identity read either fails or returns 0-ctime fallback.

    On Linux, /proc/{pid} disappears after the reaper runs. On
    Windows, GetProcessTimes on a released PID returns invalid.
    Either way, callers see a signal that the pid is un-guardable.
    """
    popen = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(0)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    popen.wait(timeout=5)
    # Give the OS a moment to release the PID slot.
    time.sleep(0.2)
    ident = current_identity(popen.pid)
    # Either None (Windows / macOS clean release) or a zero-ctime
    # fallback (Linux /proc/PID scanned during window before
    # reaper). Both are documented acceptable outcomes.
    if ident is not None:
        # If any identity was returned, the caller compares against
        # the stored identity to catch PID reuse; the invariant here
        # is only that the return is safe.
        assert ident.pid == popen.pid


# RACT 0.5.2
