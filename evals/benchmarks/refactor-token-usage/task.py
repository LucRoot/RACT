"""Refactor-token-usage benchmark task definition.

This benchmark isolates one variable: does milestone-driven termination
(RACT's loop) spend fewer tokens to reach a passing state than a naive
fixed-iteration loop?

Both runners use the SAME per-step work (the deterministic refactor edit from
the eval harness mock) and the SAME token-cost model. The only difference is
the stop policy. That keeps the comparison fair: a strawman baseline would
make the contender look good for the wrong reason.

Token model: there is no live model in CI, so token cost is a deterministic
function of work performed each step. For the refactor task the edit is
fixed, so per-step cost is constant; the variable is *how many steps* each
runner takes. That is precisely the dimension milestone termination improves.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Reuse the committed eval task as the fixture so the benchmark never drifts
# from the canonical refactor task.
TASK_DIR = Path(__file__).resolve().parents[2] / "tasks" / "refactor-function"

# Deterministic per-step token cost. Modeled as prompt + generated edit.
# The refactor edit produces ~60 lines (~380 tokens at ~6 chars/token) plus a
# fixed prompt overhead. This is a model, not a measurement; it is held
# constant across both runners so the comparison is valid.
PROMPT_TOKENS = 480
EDIT_LINES = 60
TOKENS_PER_LINE = 6.4


@dataclass(frozen=True)
class StepOutcome:
    """Result of one loop step."""

    iteration: int
    tokens_spent: float
    milestone_passed: bool


def step_token_cost() -> float:
    """Deterministic token cost of one step of the refactor task."""
    return PROMPT_TOKENS + EDIT_LINES * TOKENS_PER_LINE


def apply_refactor_edit(workspace: Path) -> None:
    """Apply the deterministic refactor edit to the workspace.

    Delegates to the eval harness mock so the benchmark uses the canonical
    edit rather than a second copy that could drift.
    """
    # Import the harness mock lazily so the benchmark module imports cleanly
    # even if the package is partially installed.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
    from ract.eval.runner import _mock_run  # type: ignore[import-not-found]

    _mock_run(TASK_DIR, workspace, seed=42)


def verify_milestone(workspace: Path) -> bool:
    """Return True if the refactor milestone is met (tests + complexity).

    Reuses the task's own success verifier so the benchmark's notion of
    "passing" is identical to the eval harness's notion.
    """
    success_script = TASK_DIR / "success.py"
    if not success_script.is_file():
        return False
    proc = subprocess.run(
        [sys.executable, str(success_script), str(workspace)],
        capture_output=True,
        text=True,
        cwd=workspace,
    )
    if proc.returncode != 0:
        return False
    try:
        outcome = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False
    return bool(outcome.get("passed", False))


def fresh_workspace(dest: Path) -> Path:
    """Copy the task fixture into ``dest`` and return it."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(TASK_DIR, dest)
    return dest


# RACT 0.3.0
