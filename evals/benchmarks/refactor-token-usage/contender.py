"""RACT milestone-driven loop runner (the benchmark contender).

Same per-step work and token model as the naive baseline, but halts as soon as
the milestone verifies — mirroring ``TerminationCause.COMPLETE`` (T1) in
``src/ract/core/loop.py``. This is the policy the benchmark is designed to
prove superior on the tokens-spent-to-passing-state dimension.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from task import (
    StepOutcome,
    apply_refactor_edit,
    fresh_workspace,
    step_token_cost,
    verify_milestone,
)


class RACTLoopRunner:
    """Run steps until the milestone passes, then halt (T1 COMPLETE)."""

    def __init__(self, max_iterations: int = 5) -> None:
        # max_iterations is a safety ceiling only; the loop is expected to
        # stop well before it via milestone verification.
        if max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        self.max_iterations = max_iterations

    def run(self) -> list[StepOutcome]:
        outcomes: list[StepOutcome] = []
        with tempfile.TemporaryDirectory(prefix="ract-bench-ract-") as tmp:
            workspace = fresh_workspace(Path(tmp) / "workspace")
            cumulative = 0.0
            apply_refactor_edit(workspace)
            for i in range(1, self.max_iterations + 1):
                cumulative += step_token_cost()
                passed = verify_milestone(workspace)
                outcomes.append(
                    StepOutcome(
                        iteration=i,
                        tokens_spent=cumulative,
                        milestone_passed=passed,
                    )
                )
                if passed:
                    # T1: all milestones verified. Halt immediately.
                    break
        return outcomes


# RACT 0.3.0
