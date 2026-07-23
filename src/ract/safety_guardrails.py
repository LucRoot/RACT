from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from ract.error_mask_detector import error_mask_violations
from ract.manager import Plan, Step

_ROOT_KNOT = object()


@dataclass
class SafetyGuardrail:
    """
    Check generated code against a configurable list of forbidden patterns.
    """

    rules: List[Dict[str, str]] = field(default_factory=list)
    check_error_masks: bool = True

    def __post_init__(self) -> None:
        for rule in self.rules:
            if "pattern" not in rule:
                raise ValueError("every rule must contain a 'pattern' key")
            if "name" not in rule:
                rule["name"] = rule["pattern"]

    def check(self, path: str, content: str) -> List[Dict[str, Any]]:
        """Return violations for a single file."""
        violations: List[Dict[str, Any]] = []
        for rule in self.rules:
            pattern = rule["pattern"]
            for match in re.finditer(pattern, content):
                violations.append(
                    {
                        "path": path,
                        "rule": rule["name"],
                        "pattern": pattern,
                        "message": rule.get(
                            "message", f"matched forbidden pattern {pattern!r}"
                        ),
                        "line": content[: match.start()].count("\n") + 1,
                    }
                )

        if self.check_error_masks and self._looks_like_python(path, content):
            for violation in error_mask_violations(content):
                violations.append(
                    {
                        "path": path,
                        "rule": violation["rule"],
                        "pattern": violation["rule"],
                        "message": violation["message"],
                        "line": violation["line"],
                    }
                )

        return violations

    @staticmethod
    def _looks_like_python(path: str, content: str) -> bool:
        """Return True if the file should be analyzed for Python-specific masks."""
        if path.endswith(".py"):
            return True
        # Heuristic for model outputs that are Python source but lack an extension.
        return (
            "def " in content
            or "class " in content
            or "import " in content
            or "from __future__ import annotations" in content
        )

    def check_files(self, files: Dict[str, str]) -> List[Dict[str, Any]]:
        """Return aggregated violations across multiple files."""
        violations: List[Dict[str, Any]] = []
        for path, content in files.items():
            violations.extend(self.check(path, content))
        return violations


_plan = Plan(
    assumption="safety_guardrails must detect forbidden patterns in generated code before files are written",
    confidence=0.95,
    steps=[
        Step(
            action="create SafetyGuardrail class with check and check_files methods",
            provider_hint="internal",
            expected_artifact="src/ract/safety_guardrails.py",
        )
    ],
)
# RACT 0.1.1 - Trust and tooling
