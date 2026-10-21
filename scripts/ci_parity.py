"""Run the lint, format and type checks of the CI ``lint-format-type`` job.

The commands are the ones in ``.github/workflows/ci.yml``. CI type-checks on
Linux; on another platform this script also runs mypy with
``--platform linux`` and ``--platform darwin`` so platform-specific branches
are checked the way CI and macOS users will see them.

Usage (from the repository root, inside the project's virtual environment)::

    python scripts/ci_parity.py

Exit code 0 when every check passes, 1 otherwise. Each failing command is
named at the end.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Keep in step with the lint-format-type job in .github/workflows/ci.yml.
CI_COMMANDS: list[list[str]] = [
    ["ruff", "check", "src", "tests", "scripts", "evals"],
    ["ruff", "format", "--check", "src", "tests", "scripts", "evals"],
    ["mypy", "src"],
]


def commands() -> list[list[str]]:
    cmds = [list(c) for c in CI_COMMANDS]
    if sys.platform != "linux":
        cmds.append(["mypy", "src", "--platform", "linux"])
    if sys.platform != "darwin":
        cmds.append(["mypy", "src", "--platform", "darwin"])
    return cmds


def main() -> int:
    failed: list[str] = []
    for cmd in commands():
        shown = " ".join(cmd)
        print(f"$ {shown}", flush=True)
        result = subprocess.run([sys.executable, "-m", *cmd], cwd=REPO)
        if result.returncode != 0:
            failed.append(shown)
    if failed:
        print("\nfailed:\n  " + "\n  ".join(failed))
        return 1
    print("\nall CI lint, format and type checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
