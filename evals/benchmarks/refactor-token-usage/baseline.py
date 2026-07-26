"""Naive fixed-iteration loop runner (the benchmark baseline).

Same per-step work and token model as the RACT contender, but runs for exactly
``max_iterations`` steps regardless of whether the milestone is already met.
This is the "naive baseline" the spec asks the milestone-driven loop to beat:
it represents an agent loop with no completion detection.
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


class NaiveLoopRunner:
    """Run ``max_iterations`` steps unconditionally, then report."""

    def __init__(self, max_iterations: int = 5) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        self.max_iterations = max_iterations

    def run(self) -> list[StepOutcome]:
        outcomes: list[StepOutcome] = []
        with tempfile.TemporaryDirectory(prefix="ract-bench-naive-") as tmp:
            workspace = fresh_workspace(Path(tmp) / "workspace")
            cumulative = 0.0
            # Apply the edit once (idempotent in the mock) and then keep
            # "working" — re-checking the milestone each step but NOT stopping
            # on it. The naive loop spends tokens every iteration regardless.
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
        return outcomes


# RACT 0.3.0
