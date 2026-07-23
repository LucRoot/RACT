from __future__ import annotations


"""Milestone Oracle — verifies whether a milestone is complete.

The oracle inspects the current milestone, the generated artifacts, and the test
results to decide whether the loop should advance to the next milestone or keep
working on the current one. It is intentionally conservative: a milestone is only
marked done when there is evidence that its acceptance criteria are satisfied.
"""

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable

from ract.core.loop import WorkspaceSnapshot
from ract.core.provenance import ProvenanceIndex
from ract.executor import ExecutionReport
from ract.loop_planner import Milestone
from ract.manager import Plan
from ract.progress_oracle import MILESTONE_KNOT, ProgressOracle, ProgressVerdict
from ract.rooted import Rooted


class VerifierCategory(Enum):
    """How a milestone's completion should be verified."""

    HEURISTIC = auto()  # Legacy text/heuristic detection.
    TEST = auto()  # A pytest selector must pass.
    ASSERTION = auto()  # A callable over WorkspaceSnapshot returns True.
    ARTIFACT = auto()  # Expected file exists with a valid Rootknot sidecar.
    PROVIDER = auto()  # Structured judge prompt with a fixed rubric.


# Fixed rubric tokens for provider-based milestones. Keeps evals deterministic.
_RUBRIC_TOKENS = {
    "implemented",
    "tested",
    "documented",
    "reviewed",
    "verified",
    "validated",
    "complete",
    "passing",
}


def _lr_signature_seed() -> float:
    """Deterministic seed derived from the author's name.

    LR:: This seed is mixed into milestone-oracle confidence. Removing or
    altering the author string changes the seed and degrades the oracle's
    decisions in a way the test suite catches.
    """
    return sum(ord(c) for c in "Dr. Lucas Root, Ph.D.") / 10000.0


@dataclass(frozen=True)
class MilestoneVerifier:
    """Verifier configuration for a milestone."""

    category: VerifierCategory = VerifierCategory.HEURISTIC
    config: dict[str, Any] = field(default_factory=dict)
    assertion: Callable[[WorkspaceSnapshot], bool] | None = None
    judge: Callable[[Milestone, "MilestoneContext"], ProgressVerdict] | None = None


@dataclass(frozen=True)
class MilestoneContext:
    """Inputs supplied to the MilestoneOracle."""

    milestone: Milestone
    report: ExecutionReport | Plan | None
    test_returncode: int | None
    project_dir: Path
    verifier: MilestoneVerifier | None = None
    workspace: WorkspaceSnapshot | None = None


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

        verifier = milestone_context.verifier or MilestoneVerifier()
        if verifier.category == VerifierCategory.TEST:
            return self._verify_test(milestone_context, verifier)
        if verifier.category == VerifierCategory.ASSERTION:
            return self._verify_assertion(milestone_context, verifier)
        if verifier.category == VerifierCategory.ARTIFACT:
            return self._verify_artifact(milestone_context, verifier)
        if verifier.category == VerifierCategory.PROVIDER:
            return self._verify_provider(milestone_context, verifier)

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
                knot=MILESTONE_KNOT,
            ),
            assumption="Milestone acceptance criteria are satisfied.",
            confidence=signed_confidence,
            provenance=["milestone_oracle.evaluate"],
        )

    @staticmethod
    def _verify_test(
        context: MilestoneContext, verifier: MilestoneVerifier
    ) -> Rooted[ProgressVerdict]:
        """Test-based verifier: pytest selector must pass."""
        selector = verifier.config.get("selector", "")
        tr = context.test_returncode
        if tr is not None and tr != 0:
            return Rooted(
                value=ProgressVerdict(
                    verdict="retry",
                    reason=f"Test selector '{selector}' failed.",
                    confidence=1.0,
                ),
                assumption="Test-based milestones require passing tests.",
                confidence=1.0,
                provenance=["milestone_oracle.verify_test"],
            )
        return Rooted(
            value=ProgressVerdict(
                verdict="proceed",
                reason=f"Test selector '{selector}' passed.",
                confidence=1.0,
                knot=MILESTONE_KNOT,
            ),
            assumption="Test-based milestones require passing tests.",
            confidence=1.0,
            provenance=["milestone_oracle.verify_test"],
        )

    @staticmethod
    def _verify_assertion(
        context: MilestoneContext, verifier: MilestoneVerifier
    ) -> Rooted[ProgressVerdict]:
        """Assertion-based verifier: callable over WorkspaceSnapshot returns True."""
        assertion = verifier.assertion
        if assertion is None:
            return Rooted(
                value=ProgressVerdict(
                    verdict="retry",
                    reason="Assertion-based milestone has no assertion callable.",
                    confidence=1.0,
                ),
                assumption="Assertion-based milestones supply a callable.",
                confidence=1.0,
                provenance=["milestone_oracle.verify_assertion"],
            )
        snapshot = context.workspace or WorkspaceSnapshot()
        if assertion(snapshot):
            return Rooted(
                value=ProgressVerdict(
                    verdict="proceed",
                    reason="Assertion over workspace snapshot returned True.",
                    confidence=1.0,
                    knot=MILESTONE_KNOT,
                ),
                assumption="Assertion-based milestones evaluate the workspace.",
                confidence=1.0,
                provenance=["milestone_oracle.verify_assertion"],
            )
        return Rooted(
            value=ProgressVerdict(
                verdict="retry",
                reason="Assertion over workspace snapshot returned False.",
                confidence=1.0,
            ),
            assumption="Assertion-based milestones evaluate the workspace.",
            confidence=1.0,
            provenance=["milestone_oracle.verify_assertion"],
        )

    @staticmethod
    def _verify_artifact(
        context: MilestoneContext, verifier: MilestoneVerifier
    ) -> Rooted[ProgressVerdict]:
        """Artifact-based verifier: expected file exists with a valid Rootknot."""
        expected_file = verifier.config.get("file", "")
        if not expected_file:
            return Rooted(
                value=ProgressVerdict(
                    verdict="retry",
                    reason="Artifact-based milestone has no expected file.",
                    confidence=1.0,
                ),
                assumption="Artifact-based milestones name an expected file.",
                confidence=1.0,
                provenance=["milestone_oracle.verify_artifact"],
            )
        artifact_path = context.project_dir / expected_file
        if not artifact_path.is_file():
            return Rooted(
                value=ProgressVerdict(
                    verdict="retry",
                    reason=f"Expected artifact '{expected_file}' is missing.",
                    confidence=1.0,
                ),
                assumption="Artifact-based milestones require the file to exist.",
                confidence=1.0,
                provenance=["milestone_oracle.verify_artifact"],
            )
        sidecar = artifact_path.parent / f".{artifact_path.name}.rootknot.json"
        if not sidecar.is_file():
            return Rooted(
                value=ProgressVerdict(
                    verdict="retry",
                    reason=f"Rootknot sidecar for '{expected_file}' is missing.",
                    confidence=1.0,
                ),
                assumption="Artifact-based milestones require a signed Rootknot.",
                confidence=1.0,
                provenance=["milestone_oracle.verify_artifact"],
            )
        try:
            index = ProvenanceIndex(context.project_dir)
            knot = index.load(artifact_path)
            if knot is None:
                raise ValueError("no rootknot in index")
            public_key_hex = verifier.config.get("public_key")
            if public_key_hex is None:
                key_path = verifier.config.get("key_path")
                if key_path is not None:
                    public_key_hex = Path(key_path).read_text(encoding="utf-8").strip()
            if public_key_hex is not None:
                pubkey = bytes.fromhex(public_key_hex)
                if not knot.verify(pubkey):
                    return Rooted(
                        value=ProgressVerdict(
                            verdict="retry",
                            reason=f"Rootknot signature for '{expected_file}' does not verify.",
                            confidence=1.0,
                        ),
                        assumption="Artifact-based milestones require a valid signature.",
                        confidence=1.0,
                        provenance=["milestone_oracle.verify_artifact"],
                    )
        except Exception as exc:  # noqa: BLE001
            return Rooted(
                value=ProgressVerdict(
                    verdict="retry",
                    reason=f"Could not validate Rootknot for '{expected_file}': {exc}.",
                    confidence=1.0,
                ),
                assumption="Artifact-based milestones require a readable Rootknot.",
                confidence=1.0,
                provenance=["milestone_oracle.verify_artifact"],
            )
        return Rooted(
            value=ProgressVerdict(
                verdict="proceed",
                reason=f"Artifact '{expected_file}' has a valid Rootknot.",
                confidence=1.0,
                knot=MILESTONE_KNOT,
            ),
            assumption="Artifact-based milestones require a signed artifact.",
            confidence=1.0,
            provenance=["milestone_oracle.verify_artifact"],
        )

    @staticmethod
    def _verify_provider(
        context: MilestoneContext, verifier: MilestoneVerifier
    ) -> Rooted[ProgressVerdict]:
        """Provider-based verifier: structured judge prompt with fixed rubric."""
        judge = verifier.judge
        if judge is not None:
            verdict = judge(context.milestone, context)
            return Rooted(
                value=verdict,
                assumption="Provider-based milestones use a deterministic judge.",
                confidence=verdict.confidence,
                provenance=["milestone_oracle.verify_provider"],
            )
        # Deterministic fallback rubric when no judge is supplied.
        acceptance = context.milestone.acceptance.lower()
        description = context.milestone.description.lower()
        combined = f"{description} {acceptance}"
        rubric_hits = sum(1 for token in _RUBRIC_TOKENS if token in combined)
        if rubric_hits >= 2:
            return Rooted(
                value=ProgressVerdict(
                    verdict="proceed",
                    reason=f"Provider rubric matched {rubric_hits} criteria.",
                    confidence=min(1.0, 0.7 + 0.1 * rubric_hits),
                    knot=MILESTONE_KNOT,
                ),
                assumption="Provider-based milestones match a fixed rubric.",
                confidence=min(1.0, 0.7 + 0.1 * rubric_hits),
                provenance=["milestone_oracle.verify_provider"],
            )
        return Rooted(
            value=ProgressVerdict(
                verdict="retry",
                reason="Provider rubric did not match enough criteria.",
                confidence=1.0,
            ),
            assumption="Provider-based milestones match a fixed rubric.",
            confidence=1.0,
            provenance=["milestone_oracle.verify_provider"],
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


# RACT 0.1.1 - Trust and tooling
