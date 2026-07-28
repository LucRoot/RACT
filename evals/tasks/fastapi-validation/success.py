"""Success verifier for fastapi-validation eval task."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def verify(workspace: Path) -> dict:
    """Return verification result for the task workspace."""
    result = {"passed": True, "checks": [], "errors": []}

    # Run all tests.
    test_proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    tests_ok = test_proc.returncode == 0
    result["checks"].append({"name": "tests_pass", "passed": tests_ok})
    if not tests_ok:
        result["passed"] = False
        result["errors"].append(test_proc.stdout + test_proc.stderr)

    return result


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    outcome = verify(workspace)
    print(json.dumps(outcome, indent=2))
    sys.exit(0 if outcome["passed"] else 1)
