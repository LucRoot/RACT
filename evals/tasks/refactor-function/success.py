"""Success verifier for refactor-function eval task."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path


def _cyclomatic_complexity(func: ast.FunctionDef) -> int:
    """Rough cyclomatic complexity: 1 + number of branches."""
    branches = 0
    for node in ast.walk(func):
        if isinstance(node, (ast.If, ast.While, ast.For)):
            branches += 1
        elif isinstance(node, ast.ExceptHandler):
            branches += 1
    return 1 + branches


def verify(workspace: Path) -> dict:
    """Return verification result for the task workspace."""
    result = {"passed": True, "checks": [], "errors": []}

    # Run tests.
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

    # Cyclomatic complexity.
    src_file = workspace / "src" / "orders.py"
    complexity_ok = True
    if src_file.is_file():
        tree = ast.parse(src_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                score = _cyclomatic_complexity(node)
                result["checks"].append(
                    {
                        "name": f"complexity_{node.name}",
                        "score": score,
                        "passed": score < 8,
                    }
                )
                if score >= 8:
                    complexity_ok = False
    else:
        complexity_ok = False
        result["errors"].append("src/orders.py missing")

    result["checks"].append({"name": "complexity_under_8", "passed": complexity_ok})
    if not complexity_ok:
        result["passed"] = False

    # Rootknot violations: just verify the .rack index does not exist or is empty.
    rack_dir = workspace / ".rack"
    rootknot_ok = not rack_dir.exists() or not any(rack_dir.iterdir())
    result["checks"].append({"name": "no_rootknot_violations", "passed": rootknot_ok})
    if not rootknot_ok:
        result["passed"] = False

    return result


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    outcome = verify(workspace)
    print(json.dumps(outcome, indent=2))
    sys.exit(0 if outcome["passed"] else 1)
