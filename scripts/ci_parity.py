"""Run the lint, format and type checks of the CI ``lint-format-type`` job.

The commands are the ones in ``.github/workflows/ci.yml``. CI type-checks on
Linux; on another platform this script also runs mypy with
``--platform linux`` and ``--platform darwin`` so platform-specific branches
are checked the way CI and macOS users will see them.

Some mypy errors come from the local environment, not the code: a dev
dependency that CI installs but this machine lacks. Those are listed as
``known-environment`` and do not fail the run; every other error does.

Usage (from the repository root, inside the project's virtual environment)::

    python scripts/ci_parity.py

Exit code 0 when every check passes, 1 otherwise. Each failing command is
named at the end.
"""

from __future__ import annotations

import re
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

# mypy error lines caused by a package missing from the local environment.
# CI installs the dev extras, so these are real types there.
KNOWN_ENVIRONMENT = {
    "multilspy not installed": re.compile(
        r'Cannot find implementation or library stub for module named "multilspy'
    ),
}

# Native-Windows mypy only: typeshed declares no readline functions on win32.
# CI runs Linux, where they exist, so these lines do not reach CI.
NATIVE_WINDOWS_ONLY = re.compile(
    r"src[\\/]ract[\\/]repl\.py:\d+: error: Module has no attribute"
)

_MYPY_ERROR = re.compile(r"^\S+:\d+: error:")


def commands() -> list[list[str]]:
    cmds = [list(c) for c in CI_COMMANDS]
    if sys.platform != "linux":
        cmds.append(["mypy", "src", "--platform", "linux"])
    if sys.platform != "darwin":
        cmds.append(["mypy", "src", "--platform", "darwin"])
    return cmds


def _run_mypy(cmd: list[str]) -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", *cmd], cwd=REPO, capture_output=True, text=True
    )
    native = cmd == ["mypy", "src"] and sys.platform == "win32"
    real: list[str] = []
    for line in proc.stdout.splitlines():
        if not _MYPY_ERROR.match(line):
            continue
        label = next(
            (k for k, rx in KNOWN_ENVIRONMENT.items() if rx.search(line)), None
        )
        if label:
            print(f"  known-environment: {label}: {line}")
        elif native and NATIVE_WINDOWS_ONLY.search(line):
            print(f"  native-windows-only: {line}")
        else:
            real.append(line)
    for line in real:
        print(f"  {line}")
    if real:
        print(f"  {len(real)} error(s) that CI would also report")
    elif proc.returncode not in (0, 1):
        print(proc.stdout + proc.stderr)
        return False
    return not real


def main() -> int:
    failed: list[str] = []
    for cmd in commands():
        shown = " ".join(cmd)
        print(f"$ {shown}", flush=True)
        if cmd[0] == "mypy":
            ok = _run_mypy(cmd)
        else:
            ok = subprocess.run([sys.executable, "-m", *cmd], cwd=REPO).returncode == 0
        if not ok:
            failed.append(shown)
    if failed:
        print("\nfailed:\n  " + "\n  ".join(failed))
        return 1
    print("\nall CI lint, format and type checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
