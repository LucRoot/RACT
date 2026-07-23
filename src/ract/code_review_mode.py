from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import re
from dataclasses import dataclass
from typing import Any, Dict, List

from ract.manager import Plan, Step

_ROOT_KNOT = object()


@dataclass
class ReviewComment:
    """A single structured code-review comment."""

    line: int
    severity: str
    category: str
    message: str
    suggestion: str
    confidence: float


class CodeReviewMode:
    """
    Produce a structured review from a diff or patch string.

    The review identifies added/removed/changed hunks, flags common risk
    patterns (security, correctness, style), and emits a structured report.
    """

    _RISK_PATTERNS: List[Dict[str, str | float]] = [
        {
            "category": "security",
            "severity": "high",
            "pattern": r"eval\s*\(",
            "message": "Potential arbitrary code execution via eval().",
            "suggestion": "Replace eval() with ast.literal_eval() or a dedicated parser.",
            "confidence": 0.9,
        },
        {
            "category": "security",
            "severity": "high",
            "pattern": r"exec\s*\(",
            "message": "Potential arbitrary code execution via exec().",
            "suggestion": "Avoid exec(); refactor to explicit, auditable code paths.",
            "confidence": 0.9,
        },
        {
            "category": "security",
            "severity": "medium",
            "pattern": r"subprocess\.\w+\([^)]*shell\s*=\s*True",
            "message": "Shell=True can enable command injection.",
            "suggestion": "Use shell=False and pass arguments as a list.",
            "confidence": 0.85,
        },
        {
            "category": "correctness",
            "severity": "medium",
            "pattern": r"except\s*:\s*$",
            "message": "Bare except: catches unexpected errors including SystemExit.",
            "suggestion": "Catch specific exceptions (e.g., except ValueError:).",
            "confidence": 0.8,
        },
        {
            "category": "style",
            "severity": "low",
            "pattern": r"print\s*\(",
            "message": "Leftover debug print statement.",
            "suggestion": "Remove debug prints or replace with structured logging.",
            "confidence": 0.6,
        },
    ]

    def __init__(
        self, extra_patterns: List[Dict[str, str | float]] | None = None
    ) -> None:
        self.patterns = list(self._RISK_PATTERNS)
        if extra_patterns:
            self.patterns.extend(extra_patterns)

    def parse_diff(self, diff: str) -> List[Dict[str, str | int]]:
        """Parse a unified diff into added-line records."""
        lines = diff.splitlines()
        records: List[Dict[str, str | int]] = []
        current_file = ""
        line_number = 0
        for line in lines:
            if line.startswith("--- ") or line.startswith("+++ "):
                continue
            file_header = re.match(r"^\+\+\+ b/(\S+)", line)
            if file_header:
                current_file = file_header.group(1)
                continue
            hunk_header = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if hunk_header:
                line_number = int(hunk_header.group(1))
                continue
            if line.startswith("+") and not line.startswith("+++"):
                records.append(
                    {
                        "file": current_file,
                        "line": line_number,
                        "content": line[1:],
                    }
                )
                line_number += 1
            elif line.startswith(" "):
                line_number += 1
        return records

    def review(self, diff: str) -> Dict[str, Any]:
        """Return a structured review of the diff."""
        records = self.parse_diff(diff)
        comments: List[ReviewComment] = []
        for record in records:
            content = str(record["content"])
            line = int(record["line"])
            for rule in self.patterns:
                pattern = str(rule["pattern"])
                if re.search(pattern, content):
                    comments.append(
                        ReviewComment(
                            line=line,
                            severity=str(rule["severity"]),
                            category=str(rule["category"]),
                            message=str(rule["message"]),
                            suggestion=str(rule["suggestion"]),
                            confidence=float(rule["confidence"]),
                        )
                    )

        summary = self._summarize(comments)
        return {
            "files_changed": sorted({str(r["file"]) for r in records}),
            "lines_added": len(records),
            "comments": [self._comment_to_dict(c) for c in comments],
            "summary": summary,
        }

    def _comment_to_dict(self, comment: ReviewComment) -> Dict[str, object]:
        return {
            "line": comment.line,
            "severity": comment.severity,
            "category": comment.category,
            "message": comment.message,
            "suggestion": comment.suggestion,
            "confidence": comment.confidence,
        }

    def _summarize(self, comments: List[ReviewComment]) -> str:
        if not comments:
            return "No obvious risks detected."
        counts: Dict[str, int] = {}
        for c in comments:
            counts[c.severity] = counts.get(c.severity, 0) + 1
        parts = [f"{n} {sev}" for sev, n in sorted(counts.items())]
        return f"Review found {len(comments)} comment(s): {', '.join(parts)}."


_plan = Plan(
    assumption="code_review_mode must parse diffs and produce structured risk comments",
    confidence=0.95,
    steps=[
        Step(
            action="create CodeReviewMode class with parse_diff and review methods",
            provider_hint="internal",
            expected_artifact="src/ract/code_review_mode.py",
        )
    ],
)
# RACT 0.1.1 - Trust and tooling
