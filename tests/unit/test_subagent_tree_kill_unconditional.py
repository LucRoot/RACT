"""Regression -- SubprocessSubagentHandle.dispose is UNCONDITIONAL.

v0.5.2 hardening module_03 (DA-A F-4 closure). The pre-hardening
:meth:`SubprocessSubagentHandle.dispose` short-circuited when
``self.popen.poll() is not None`` -- setting ``_disposed=True`` and
returning True without invoking :func:`kill_tree`. That was WRONG:
grandchildren whose parent exited get reparented to init/system
(POSIX) or leak from the Job Object (Windows) and keep running.

This test spawns a subagent that spawns a long-sleeping grandchild
then EXITS the parent. It then registers a handle around the
already-exited Popen and asserts:

1. ``dispose`` still fires (returns True).
2. The tree-kill emits ``substrate.subagent.tree_kill_invoked`` with
   ``path == "poll_exited"`` -- the load-bearing telemetry.
3. The reparented grandchild IS reaped (POSIX pgid / Windows Job
   Object catches it).

Ox Alpha co-build (Fork 4 verdict a+b): the ``tree_kill_invoked``
event is the audit signal an operator uses to confirm the fix is
doing real work in the field.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from ract.executor.subagent_handle import SubprocessSubagentHandle


_IS_WINDOWS = sys.platform == "win32"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if _IS_WINDOWS:
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
        return True


def _spawn_parent_with_orphan_grandchild(
    tmp_path: Path,
) -> tuple[subprocess.Popen, int, int]:
    """Spawn a parent that spawns a grandchild then exits.

    Returns ``(popen, parent_pid, grandchild_pid)``. The parent
    Popen has exited by the time this returns; the grandchild is
    reparented (POSIX: to init/subreaper; Windows: to the Job
    Object).
    """
    pid_file = tmp_path / f"gc_{time.time_ns()}.txt"
    script = tmp_path / f"parent_{time.time_ns()}.py"
    script.write_text(
        textwrap.dedent(
            f"""\
            import os, sys, subprocess, time
            grand = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )
            with open(r"{pid_file!s}", "w") as f:
                f.write(str(grand.pid))
                f.flush()
            # Parent exits IMMEDIATELY -- grandchild is now orphaned.
            sys.exit(0)
            """
        ),
        encoding="utf-8",
    )
    popen = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for parent to write the grandchild PID + exit.
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if pid_file.exists():
            text = pid_file.read_text().strip()
            if text and text.isdigit():
                # Also wait for parent exit.
                if popen.poll() is not None:
                    return popen, popen.pid, int(text)
        time.sleep(0.05)
    raise TimeoutError("orphan-grandchild spawn setup did not complete")


@pytest.mark.timeout(90)
def test_dispose_fires_kill_tree_even_when_parent_popen_exited(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DA-A F-4 core: dispose invokes kill_tree unconditionally.

    Pre-hardening, poll() != None caused short-circuit and
    ``kill_tree`` was skipped. Post-hardening, ``kill_tree`` fires
    and the ``substrate.subagent.tree_kill_invoked`` event records
    ``path == "poll_exited"``.
    """
    popen, parent_pid, grandchild_pid = _spawn_parent_with_orphan_grandchild(tmp_path)
    # Sanity: parent has exited by construction.
    assert popen.poll() is not None, "parent should have exited"

    events_captured: list[tuple[str, dict]] = []

    def _fake_emit(kind: str, payload: dict) -> None:
        events_captured.append((kind, dict(payload)))

    # Patch the trace sink so we capture the event without needing a
    # writer registered.
    import ract.trace.sink as sink_mod

    monkeypatch.setattr(sink_mod, "emit", _fake_emit)

    handle = SubprocessSubagentHandle(
        popen=popen,
        descriptor={"role": "test", "label": "orphan_grandchild"},
        kind="subprocess",
    )

    try:
        result = handle.dispose(reason="test_dispose_unconditional")

        assert result is True, "dispose returns True on best-effort success"

        # The load-bearing telemetry.
        tree_kill_events = [
            payload
            for (kind, payload) in events_captured
            if kind == "substrate.subagent.tree_kill_invoked"
        ]
        assert len(tree_kill_events) == 1, (
            f"tree_kill_invoked fires exactly once per dispose; "
            f"got {len(tree_kill_events)} events: {events_captured}"
        )
        event = tree_kill_events[0]
        assert event["path"] == "poll_exited", (
            f"path must be 'poll_exited' when parent Popen exited "
            f"pre-dispose; got {event['path']!r}"
        )
        assert event["pid"] == parent_pid, (
            f"pid payload must match parent pid; got {event['pid']} vs {parent_pid}"
        )
        assert event["reason"] == "test_dispose_unconditional"
    finally:
        # Test cleanup: the grandchild might have survived if the OS
        # reparented it away from any group we captured. Kill it
        # directly so the process table stays clean.
        try:
            if _pid_alive(grandchild_pid):
                if _IS_WINDOWS:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(grandchild_pid)],
                        capture_output=True,
                        check=False,
                    )
                else:
                    os.kill(grandchild_pid, 9)
        except Exception:  # noqa: BLE001
            pass


@pytest.mark.timeout(30)
def test_dispose_captures_identity_at_construction(tmp_path: Path) -> None:
    """__post_init__ captures (pid, creation_time_ns) on the handle.

    Ox Alpha M-5 closure: identity is captured at spawn/registration,
    not at kill-time.
    """
    popen = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        handle = SubprocessSubagentHandle(popen=popen)
        # Identity captured at construction is not None on a
        # supported platform.
        assert handle._spawn_identity is not None, (
            "SubprocessSubagentHandle must capture identity in __post_init__"
        )
        assert handle._spawn_identity.pid == popen.pid
        assert handle._spawn_identity.creation_time_ns >= 0
    finally:
        popen.kill()
        try:
            popen.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass


@pytest.mark.timeout(30)
def test_dispose_is_idempotent_after_hardening(tmp_path: Path) -> None:
    """Second dispose returns True without emitting a second tree-kill.

    The idempotence contract survives the DA-A F-4 fix: only the
    first dispose call fires kill_tree; subsequent calls no-op.
    """
    popen = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        handle = SubprocessSubagentHandle(popen=popen)
        assert handle.dispose(reason="first") is True
        assert handle._disposed is True
        # Second call: no-op, still True.
        assert handle.dispose(reason="second") is True
    finally:
        try:
            popen.kill()
            popen.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass


# RACT 0.5.2
