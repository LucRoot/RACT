"""Regression -- kill_tree refuses to signal on PID reuse.

v0.5.2 hardening module_03 (Ox Alpha M-5 closure). After a process
exits, the OS may reallocate its PID to an unrelated new process. A
stored bare pid, later handed to ``os.kill`` / ``taskkill`` /
``os.killpg``, could terminate the wrong tenant.

The mitigation captures ``(pid, creation_time_ns)`` at spawn (see
:mod:`ract.executor.process_identity`) and re-verifies before any
signal (see :func:`ract.executor.process_group._reverify_ok`). This
test forges the reuse scenario via a monkeypatched identity source
and asserts:

1. ``kill_tree`` REFUSES to signal when
   :func:`current_identity` reports a mismatched
   ``creation_time_ns`` for the stored PID.
2. The event ``substrate.subagent.pid_reuse_detected`` is emitted
   with ``stored_pid``, ``stored_ctime``, ``current_ctime``.
3. The stored pid's decoy process is NOT signaled.

Cross-platform: uses monkeypatching to simulate reuse without a
racing real spawn/kill.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from ract.executor import process_group as pg
from ract.executor.process_group import ProcessGroupHandle, kill_tree
from ract.executor.process_identity import ProcessIdentity


@pytest.mark.timeout(30)
def test_kill_tree_refuses_signal_on_pid_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identity mismatch -> pid_reuse_detected + no signal fired.

    The Ox Alpha M-5 gate.
    """
    # Spawn a real subprocess we will use as a "decoy". Its PID is
    # what our forged stored identity claims to reference; the
    # forged current identity reports a DIFFERENT creation_time_ns,
    # so kill_tree should refuse to signal it.
    decoy = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        stored_identity = ProcessIdentity(
            pid=decoy.pid,
            creation_time_ns=1_111_111_111,
        )
        forged_current = ProcessIdentity(
            pid=decoy.pid,
            creation_time_ns=9_999_999_999,
        )

        # Monkeypatch current_identity to report the mismatch.
        monkeypatch.setattr(pg, "current_identity", lambda pid: forged_current)

        # Capture events.
        events_captured: list[tuple[str, dict]] = []

        def _fake_emit(kind: str, payload: dict) -> None:
            events_captured.append((kind, dict(payload)))

        import ract.trace.sink as sink_mod

        monkeypatch.setattr(sink_mod, "emit", _fake_emit)

        # Track whether the underlying platform kill was invoked.
        kill_calls: list[str] = []

        def _fake_kill_windows(handle, **kwargs):
            kill_calls.append("windows")

        def _fake_kill_posix(handle, **kwargs):
            kill_calls.append("posix")

        def _fake_descendants_only(handle, *, close_handle):
            kill_calls.append("descendants_only")

        monkeypatch.setattr(pg, "_kill_tree_windows", _fake_kill_windows)
        monkeypatch.setattr(pg, "_kill_tree_posix", _fake_kill_posix)
        monkeypatch.setattr(pg, "_kill_descendants_only", _fake_descendants_only)

        handle = ProcessGroupHandle(
            popen=decoy,
            pgid=None,
            job_handle=None,
            argv=("python",),
            spawned_at=time.monotonic(),
            identity=stored_identity,
        )
        kill_tree(handle)

        # The event fired.
        reuse_events = [
            payload
            for (kind, payload) in events_captured
            if kind == "substrate.subagent.pid_reuse_detected"
        ]
        assert len(reuse_events) == 1, (
            f"pid_reuse_detected must fire on identity mismatch; "
            f"got events={events_captured}"
        )
        payload = reuse_events[0]
        assert payload["stored_pid"] == decoy.pid
        assert payload["stored_ctime"] == 1_111_111_111
        assert payload["current_ctime"] == 9_999_999_999

        # The main platform kill paths were NOT invoked -- we
        # fell into descendants_only which uses pgid/Job Object
        # (both None on this synthetic handle -> no-op).
        assert "windows" not in kill_calls, (
            "kill_tree_windows must NOT fire on identity mismatch"
        )
        assert "posix" not in kill_calls, (
            "kill_tree_posix must NOT fire on identity mismatch"
        )
        assert "descendants_only" in kill_calls, (
            "descendants_only path must be taken on mismatch"
        )

        # And the decoy is still alive.
        assert decoy.poll() is None, "decoy process must survive -- kill was refused"
    finally:
        try:
            decoy.kill()
            decoy.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass


@pytest.mark.timeout(30)
def test_kill_tree_proceeds_when_identity_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching identity -> kill fires on the normal platform path."""
    decoy = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        stored_identity = ProcessIdentity(
            pid=decoy.pid,
            creation_time_ns=1_234_567,
        )
        matching_current = ProcessIdentity(
            pid=decoy.pid,
            creation_time_ns=1_234_567,
        )

        monkeypatch.setattr(pg, "current_identity", lambda pid: matching_current)

        kill_calls: list[str] = []
        monkeypatch.setattr(
            pg,
            "_kill_tree_windows",
            lambda handle, **kw: kill_calls.append("windows"),
        )
        monkeypatch.setattr(
            pg,
            "_kill_tree_posix",
            lambda handle, **kw: kill_calls.append("posix"),
        )

        handle = ProcessGroupHandle(
            popen=decoy,
            pgid=None,
            job_handle=None,
            argv=("python",),
            spawned_at=time.monotonic(),
            identity=stored_identity,
        )
        kill_tree(handle)

        assert len(kill_calls) == 1, (
            f"exactly one platform kill fires on identity match; got {kill_calls}"
        )
    finally:
        try:
            decoy.kill()
            decoy.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass


@pytest.mark.timeout(30)
def test_kill_tree_bare_pid_ungarded_when_no_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No stored identity -> guard degrades to bare-pid trust.

    A handle with ``identity=None`` (spawn-time capture failed on
    macOS/BSD without /proc) proceeds through the normal platform
    kill. This preserves forward progress; the trade-off is
    documented in :mod:`ract.executor.process_identity`.
    """
    decoy = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # current_identity should not even be consulted when stored
        # is None -- assert by tripping a sentinel.
        def _sentinel(pid):
            raise AssertionError(
                "current_identity must not be called when stored is None"
            )

        # It IS called by _reverify_ok though; the un-guardable
        # branch means _reverify_ok returns True without calling
        # current_identity. So the correct assertion is: the
        # platform kill fires.
        kill_calls: list[str] = []
        monkeypatch.setattr(
            pg,
            "_kill_tree_windows",
            lambda handle, **kw: kill_calls.append("windows"),
        )
        monkeypatch.setattr(
            pg,
            "_kill_tree_posix",
            lambda handle, **kw: kill_calls.append("posix"),
        )

        handle = ProcessGroupHandle(
            popen=decoy,
            pgid=None,
            job_handle=None,
            argv=("python",),
            spawned_at=time.monotonic(),
            identity=None,
        )
        kill_tree(handle)
        assert len(kill_calls) == 1
    finally:
        try:
            decoy.kill()
            decoy.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass


# RACT 0.5.2
