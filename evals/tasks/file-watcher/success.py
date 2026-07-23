"""Success verifier for file-watcher eval task."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from pathlib import Path


def verify(workspace: Path) -> dict:
    """Return verification result for the task workspace."""
    result = {"passed": True, "checks": [], "errors": []}

    watcher = workspace / "watch.py"
    if not watcher.is_file():
        result["passed"] = False
        result["errors"].append("watch.py not found")
        result["checks"].append({"name": "watch_script_exists", "passed": False})
        return result
    result["checks"].append({"name": "watch_script_exists", "passed": True})

    # Start watcher.
    proc = subprocess.Popen(
        [sys.executable, str(watcher)],
        cwd=workspace,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.2)

    # Trigger a change.
    src_file = workspace / "src" / "page.md"
    src_file.write_text("# Updated\n", encoding="utf-8")
    start = time.time()
    rebuilt = False
    while time.time() - start < 0.6:
        if (workspace / "site" / "index.html").is_file():
            content = (workspace / "site" / "index.html").read_text(encoding="utf-8")
            if "Updated" in content:
                rebuilt = True
                break
        time.sleep(0.05)

    result["checks"].append({"name": "rebuild_within_500ms", "passed": rebuilt})
    if not rebuilt:
        result["passed"] = False
        result["errors"].append("watcher did not rebuild within 500ms")

    # SIGINT handling. On Unix we send SIGINT; on Windows signal delivery to a
    # subprocess is platform-limited, so we verify graceful termination instead.
    if proc.poll() is None:
        if sys.platform == "win32":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=2.0)
        if sys.platform == "win32":
            clean_exit = proc.returncode is not None
        else:
            clean_exit = proc.returncode == 0 or proc.returncode == -signal.SIGINT
    except subprocess.TimeoutExpired:
        proc.kill()
        clean_exit = False

    result["checks"].append({"name": "clean_sigint_exit", "passed": clean_exit})
    if not clean_exit:
        result["passed"] = False
        result["errors"].append("watcher did not exit cleanly on SIGINT")

    return result


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    outcome = verify(workspace)
    print(json.dumps(outcome, indent=2))
    sys.exit(0 if outcome["passed"] else 1)
