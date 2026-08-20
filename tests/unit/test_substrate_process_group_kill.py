"""SubstrateLoop process-group SIGKILL -- unit tests (v0.5.1 module_05).

Locks REVIEW_4_UNKNOWN §B3: rollback SIGKILL must reap the parent AND
every descendant spawned inside the step. Spawning parent -> child ->
grandchild via ``ract.executor.process_group.spawn`` then calling
``kill_tree`` on the parent's handle must leave zero surviving
processes from the tree.

Platform notes:

- POSIX: uses ``os.setsid()`` + ``os.killpg(pgid, SIGKILL)``. The
  parent/child/grandchild chain is a python subprocess that
  ``os.fork``s twice.
- Windows: uses ``CREATE_NEW_PROCESS_GROUP`` + Job Object + fallback
  ``taskkill /F /T``. The chain is one ``python`` that spawns two
  subprocesses via ``subprocess.Popen`` (Windows has no fork).

Both branches assert the same outcome: three processes started, all
three reaped after ``kill_tree``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from ract.executor.process_group import (
    kill_tree,
    spawn,
)


_IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    """Cross-platform ``kill -0``-style liveness probe."""
    if pid <= 0:
        return False
    if _IS_WINDOWS:
        # Use tasklist to check. Returns "INFO: No tasks..." when dead.
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # PID exists but we don't have permission -- treat as alive.
        return True


def _chain_script(pid_file: Path) -> str:
    """Return a python source that spawns parent -> child -> grandchild.

    Each process writes its PID to ``pid_file`` (append mode, one line
    each: ``<role>:<pid>``) then sleeps for 30 seconds. The parent
    survives the two spawns and exits after its own sleep -- but
    kill_tree fires long before then.
    """
    script = f"""\
import os, sys, time, subprocess
pf = r"{pid_file!s}"
role = sys.argv[1] if len(sys.argv) > 1 else "parent"
with open(pf, "a") as f:
    f.write(role + ":" + str(os.getpid()) + "\\n")
    f.flush()
if role == "parent":
    child = subprocess.Popen([sys.executable, __file__, "child"])
    time.sleep(30)
elif role == "child":
    grandchild = subprocess.Popen([sys.executable, __file__, "grandchild"])
    time.sleep(30)
else:
    time.sleep(30)
"""
    return textwrap.dedent(script)


def _read_pids(pid_file: Path, expected: int, timeout: float = 10.0) -> dict[str, int]:
    """Wait until ``pid_file`` has ``expected`` lines; return dict."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pid_file.exists():
            lines = [
                line.strip()
                for line in pid_file.read_text().splitlines()
                if line.strip()
            ]
            if len(lines) >= expected:
                out: dict[str, int] = {}
                for line in lines[:expected]:
                    role, _, pid_str = line.partition(":")
                    out[role] = int(pid_str)
                return out
        time.sleep(0.1)
    raise TimeoutError(
        f"expected {expected} pid lines in {pid_file}, got "
        f"{pid_file.read_text() if pid_file.exists() else '<missing>'}"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.timeout(60)
def test_kill_tree_reaps_parent_child_grandchild(tmp_path: Path) -> None:
    """Spawn a 3-deep tree; kill_tree(parent) reaps all three."""
    pid_file = tmp_path / "pids.txt"
    script_file = tmp_path / "chain.py"
    script_file.write_text(_chain_script(pid_file), encoding="utf-8")

    handle = spawn(
        [sys.executable, str(script_file), "parent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        pids = _read_pids(pid_file, expected=3, timeout=15.0)
        assert "parent" in pids and "child" in pids and "grandchild" in pids
        # All three currently alive.
        for role, pid in pids.items():
            assert _pid_alive(pid), f"{role} pid {pid} not alive before kill"

        kill_tree(handle)

        # Poll for reap (Windows Job Object is atomic but tasklist may
        # lag briefly; POSIX SIGKILL is immediate).
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if not any(_pid_alive(pid) for pid in pids.values()):
                break
            time.sleep(0.2)

        survivors = {
            role: pid for role, pid in pids.items() if _pid_alive(pid)
        }
        assert not survivors, (
            f"processes survived kill_tree: {survivors}. This is the "
            "REVIEW_4_UNKNOWN §B3 defect the module_05 fix targets."
        )
    finally:
        # Defensive: if the test raised, still try to reap.
        if handle.is_running():
            try:
                kill_tree(handle)
            except Exception:  # noqa: BLE001
                pass


def test_kill_tree_idempotent_on_dead_tree() -> None:
    """Reaping an already-dead tree is a no-op, not an error."""
    handle = spawn(
        [sys.executable, "-c", "pass"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    handle.popen.wait(timeout=5)
    # Now already dead; kill_tree must not raise.
    kill_tree(handle)
    kill_tree(handle)  # double-reap also safe


def test_spawn_returns_handle_with_platform_appropriate_group_id() -> None:
    handle = spawn(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if _IS_WINDOWS:
            assert handle.pgid is None
            # Job handle is best-effort; either handle or fallback path
            # must be available.
            # (We do not assert non-None because pywin32 may be absent.)
        else:
            assert handle.pgid == handle.popen.pid, (
                "POSIX spawn must set pgid == pid (setsid via "
                "start_new_session=True)"
            )
    finally:
        kill_tree(handle)


@pytest.mark.skipif(_IS_WINDOWS, reason="POSIX-specific reaper path")
def test_kill_tree_posix_grace_period_sends_sigterm_then_sigkill(
    tmp_path: Path,
) -> None:
    """A grace period first sends SIGTERM; process gets to run a handler.

    We spawn a python that installs a SIGTERM handler that writes a
    sentinel file before exiting. If the handler fires, the file
    exists after kill_tree with grace_period > 0.
    """
    sentinel = tmp_path / "sigterm-received.txt"
    script = f"""\
import signal, sys, time
def handler(signum, frame):
    open(r"{sentinel!s}", "w").write("caught")
    sys.exit(0)
signal.signal(signal.SIGTERM, handler)
time.sleep(30)
"""
    handle = spawn(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Give the child a moment to install the handler.
    time.sleep(0.5)
    kill_tree(handle, grace_period_seconds=2.0)
    assert sentinel.exists(), (
        "SIGTERM handler did not fire; grace period is broken"
    )


# RACT 0.5.1
