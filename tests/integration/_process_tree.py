"""Kill a process and its children, for the kill-and-resume tests (B-066).

Windows uses ``taskkill /T /F``; POSIX sends SIGKILL to the process group
the child was started in (``start_new_session=True``). Neither path is a
graceful stop: the point of the test is that the run gets no chance to
clean up.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys


def can_kill_tree() -> bool:
    """True when this platform has a process-tree kill the tests can use."""
    if sys.platform == "win32":
        return _has_taskkill()
    return hasattr(os, "killpg")


def _has_taskkill() -> bool:
    try:
        subprocess.run(["taskkill", "/?"], capture_output=True, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def kill_tree(proc: subprocess.Popen[bytes] | subprocess.Popen[str]) -> None:
    """Kill *proc* and everything it started, then wait for it to end."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
            timeout=60,
        )
    else:
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=60)
