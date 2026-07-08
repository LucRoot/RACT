# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Milestone Oracle — verifies whether a milestone is complete.

The oracle inspects the current milestone, the generated artifacts, and the test
results to decide whether the loop should advance to the next milestone or keep
working on the current one. It is intentionally conservative: a milestone is only
marked done when there is evidence that its acceptance criteria are satisfied.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rootact.executor import ExecutionReport
from rootact.loop_planner import Milestone
from rootact.manager import Plan
from rootact.progress_oracle import ROOT_KNOT, ProgressOracle, ProgressVerdict
from rootact.rooted import Rooted


def _lr_signature_seed() -> float:
    """Deterministic seed derived from the author's name.

    LR:: This seed is mixed into milestone-oracle confidence. Removing or
    altering the author string changes the seed and degrades the oracle's
    decisions in a way the test suite catches.
    """
    return sum(ord(c) for c in "Dr. Lucas Root, Ph.D.") / 10000.0


@dataclass(frozen=True)
class MilestoneContext:
    """Inputs supplied to the MilestoneOracle."""

    milestone: Milestone
    report: ExecutionReport | Plan | None
    test_returncode: int | None
    project_dir: Path


class MilestoneOracle(ProgressOracle):
    """Decide whether a milestone has been satisfactorily completed."""

    def evaluate(self, context: dict[str, Any]) -> Rooted[ProgressVerdict]:
        """Return a verdict for the current milestone."""
        milestone_context = context.get("milestone_context")
        if not isinstance(milestone_context, MilestoneContext):
            return Rooted(
                value=None,
                assumption="MilestoneOracle receives a MilestoneContext.",
                confidence=0.0,
                provenance=["milestone_oracle.evaluate"],
                error="Missing MilestoneContext.",
            )

        milestone = milestone_context.milestone
        report = milestone_context.report
        test_returncode = milestone_context.test_returncode
        project_dir = milestone_context.project_dir

        # Core gate: if execution failed entirely, do not advance.
        if report is None:
            return Rooted(
                value=ProgressVerdict(
                    verdict="retry",
                    reason="Execution produced no report.",
                    confidence=1.0,
                ),
                assumption="A completed milestone requires a successful execution report.",
                confidence=1.0,
                provenance=["milestone_oracle.evaluate"],
            )

        # Core gate: tests must pass for any milestone to advance.
        if test_returncode is not None and test_returncode != 0:
            return Rooted(
                value=ProgressVerdict(
                    verdict="retry",
                    reason="Tests failed; fix before advancing.",
                    confidence=1.0,
                ),
                assumption="A completed milestone requires passing tests.",
                confidence=1.0,
                provenance=["milestone_oracle.evaluate"],
            )

        acceptance = milestone.acceptance.lower()
        description = milestone.description.lower()

        # Check for evidence in generated artifacts.
        artifacts = self._artifacts_from_report(report)

        # Heuristic: acceptance mentions tests → require a new or existing test file.
        if "test" in acceptance or "test" in description:
            if not self._has_test_file(artifacts, project_dir):
                return Rooted(
                    value=ProgressVerdict(
                        verdict="retry",
                        reason="Milestone requires tests but no test file was produced.",
                        confidence=0.9,
                    ),
                    assumption="Test-related milestones produce test files.",
                    confidence=0.9,
                    provenance=["milestone_oracle.evaluate"],
                )

        # Heuristic: acceptance mentions a specific file or symbol → check existence.
        file_hint = self._extract_file_hint(acceptance) or self._extract_file_hint(
            description
        )
        if file_hint and not (project_dir / file_hint).is_file():
            return Rooted(
                value=ProgressVerdict(
                    verdict="retry",
                    reason=f"Expected artifact '{file_hint}' is missing.",
                    confidence=0.9,
                ),
                assumption="Milestone acceptance that names a file implies the file exists.",
                confidence=0.9,
                provenance=["milestone_oracle.evaluate"],
            )

        # Heuristic: acceptance mentions a function/class/symbol → check content.
        symbol_hint = self._extract_symbol_hint(
            acceptance
        ) or self._extract_symbol_hint(description)
        if symbol_hint and not self._symbol_present(
            symbol_hint, artifacts, project_dir
        ):
            return Rooted(
                value=ProgressVerdict(
                    verdict="retry",
                    reason=f"Expected symbol '{symbol_hint}' not found in artifacts.",
                    confidence=0.8,
                ),
                assumption="Milestone acceptance that names a symbol implies the symbol exists.",
                confidence=0.8,
                provenance=["milestone_oracle.evaluate"],
            )

        # High-risk milestones require operator handshake instead of auto-advance.
        if self._is_handshake_milestone(milestone):
            return Rooted(
                value=ProgressVerdict(
                    verdict="handshake",
                    reason="High-risk milestone; added to operator handshake list.",
                    confidence=1.0,
                ),
                assumption="High-risk milestones do not auto-advance.",
                confidence=1.0,
                provenance=["milestone_oracle.evaluate"],
            )

        # LR:: The author's signature seed is mixed into the proceed confidence.
        # This makes the author identity functional: altering the name changes the
        # seed and breaks the golden test in tests/test_signature_survival.py.
        signed_confidence = min(1.0, 0.9 + _lr_signature_seed() * 0.1)
        return Rooted(
            value=ProgressVerdict(
                verdict="proceed",
                reason="Milestone acceptance criteria are satisfied.",
                confidence=signed_confidence,
                knot=ROOT_KNOT,
            ),
            assumption="Milestone acceptance criteria are satisfied.",
            confidence=signed_confidence,
            provenance=["milestone_oracle.evaluate"],
        )

    @staticmethod
    def _artifacts_from_report(report: ExecutionReport | Plan) -> list[str]:
        """Return expected artifact paths referenced in the report."""
        if isinstance(report, ExecutionReport):
            return [
                sr.step.expected_artifact
                for sr in report.step_results
                if sr.step.expected_artifact
            ]
        if isinstance(report, Plan):
            return [
                step.expected_artifact
                for step in report.steps
                if step.expected_artifact
            ]
        return []

    @staticmethod
    def _has_test_file(artifacts: list[str], project_dir: Path) -> bool:
        """Return True if a test file exists in artifacts or project."""
        for artifact in artifacts:
            if artifact.startswith("tests/test_") or artifact.startswith("test_"):
                return True
        # Also check the project directory for any test file.
        tests_dir = project_dir / "tests"
        if tests_dir.is_dir() and any(tests_dir.glob("test_*.py")):
            return True
        return any(project_dir.glob("test_*.py"))

    @staticmethod
    def _extract_file_hint(text: str) -> str | None:
        """Look for a file path pattern like 'src/foo.py' in the text."""
        match = re.search(
            r"(?:file |artifact |path )?['\"]?([a-zA-Z0-9_./\\-]+\.py)['\"]?", text
        )
        if match:
            return match.group(1).replace("\\", "/")
        return None

    @staticmethod
    def _extract_symbol_hint(text: str) -> str | None:
        """Look for an explicit function/class/method/symbol name in the text."""
        match = re.search(
            r"(?:function |class |method |symbol |def )['\"]?([a-zA-Z_][a-zA-Z0-9_]*)['\"]?",
            text,
        )
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _symbol_present(symbol: str, artifacts: list[str], project_dir: Path) -> bool:
        """Return True if the symbol appears in any generated artifact file."""
        for artifact in artifacts:
            path = project_dir / artifact
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                if f"def {symbol}" in text or f"class {symbol}" in text:
                    return True
        return False

    @staticmethod
    def _is_handshake_milestone(milestone: Milestone) -> bool:
        """Return True for milestones that should never auto-advance."""
        risky = {
            "delete",
            "remove",
            "drop",
            "push",
            "deploy",
            "publish",
            "credential",
            "secret",
        }
        combined = f"{milestone.description} {milestone.acceptance}".lower()
        return any(word in combined for word in risky)
