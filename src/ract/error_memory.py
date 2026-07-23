# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Failure-pattern memory for the RACT self-recursing loop.

Raw pytest output is too noisy to replay into the model context every iteration.
ErrorMemory distills repeated failures into compact patterns ("generated tests
keep missing import re", "Root Knot omitted from new files", "provider timeouts
after ~60s") and surfaces them as loop memory so the management model can avoid
the same trap twice.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FailurePattern:
    """A distilled, reusable description of a failure the loop has seen."""

    category: str
    pattern: str
    iteration: int
    timestamp: str


class ErrorMemory:
    """Record, summarize, and replay failure patterns across loop iterations."""

    MAX_STORED = 200
    SUMMARY_LIMIT = 5

    def __init__(self, project_dir: Path | str, max_stored: int = MAX_STORED) -> None:
        self.project_dir = Path(project_dir)
        self.memory_path = self.project_dir / ".ract" / "error_memory.jsonl"
        self.max_stored = max(max_stored, 1)

    def _ensure_dir(self) -> None:
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict[str, Any]]:
        if not self.memory_path.is_file():
            return []
        try:
            with self.memory_path.open(encoding="utf-8") as fh:
                return [json.loads(line) for line in fh if line.strip()]
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, entries: list[dict[str, Any]]) -> None:
        self._ensure_dir()
        # Keep only the most recent entries under the cap.
        kept = entries[-self.max_stored :]
        self.memory_path.write_text(
            "".join(json.dumps(e) + "\n" for e in kept),
            encoding="utf-8",
        )

    def _extract_patterns(self, iteration: Any) -> list[FailurePattern]:
        """Distill one or more failure patterns from a LoopIteration-like object."""
        patterns: list[FailurePattern] = []
        index = getattr(iteration, "index", 0)
        test_output = getattr(iteration, "test_output", "") or ""
        error = getattr(iteration, "error", "") or ""
        reflection = getattr(iteration, "reflection", "") or ""
        knot_status = getattr(iteration, "knot_status", {}) or {}
        timestamp = datetime.now(timezone.utc).isoformat()

        # Missing Root Knot sentinel.
        missing_knot = knot_status.get("missing_knot", [])
        if missing_knot:
            patterns.append(
                FailurePattern(
                    category="signature",
                    pattern="Root Knot sentinel missing from generated artifact(s)",
                    iteration=index,
                    timestamp=timestamp,
                )
            )

        # Provider/iteration timeout.
        if "timed out" in error.lower() or "timed out" in reflection.lower():
            patterns.append(
                FailurePattern(
                    category="timeout",
                    pattern="Loop iteration or provider call timed out",
                    iteration=index,
                    timestamp=timestamp,
                )
            )

        # Missing imports in generated tests (preflight or pytest).
        import_match = re.search(
            r"missing imports for modules used in tests: ([^\.]+)", test_output, re.I
        )
        if import_match:
            modules = import_match.group(1).strip()
            patterns.append(
                FailurePattern(
                    category="preflight",
                    pattern=f"Generated test missing imports: {modules}",
                    iteration=index,
                    timestamp=timestamp,
                )
            )

        # Syntax error in generated artifact.
        if (
            "syntax error" in test_output.lower()
            or "syntax error" in reflection.lower()
        ):
            patterns.append(
                FailurePattern(
                    category="syntax",
                    pattern="Syntax error in generated artifact",
                    iteration=index,
                    timestamp=timestamp,
                )
            )

        # Refactor tax breach.
        if "refactor tax" in reflection.lower():
            patterns.append(
                FailurePattern(
                    category="refactor",
                    pattern="Refactor tax threshold breached",
                    iteration=index,
                    timestamp=timestamp,
                )
            )

        # Pytest failures: extract the first failing test name and reason.
        if test_output and "failed" in test_output.lower():
            fail_match = re.search(r"FAILED\s+(\S+)\s+-\s+(.+?)(?:\n|$)", test_output)
            if fail_match:
                test_name = fail_match.group(1)
                reason = fail_match.group(2).strip()
                patterns.append(
                    FailurePattern(
                        category="test",
                        pattern=f"Test failure: {test_name} ({reason})",
                        iteration=index,
                        timestamp=timestamp,
                    )
                )
            else:
                patterns.append(
                    FailurePattern(
                        category="test",
                        pattern="Pytest reported failures (details unavailable)",
                        iteration=index,
                        timestamp=timestamp,
                    )
                )

        return patterns

    def record(self, iteration: Any) -> list[FailurePattern]:
        """Extract patterns from an iteration and persist them.

        Returns the patterns recorded for this call.
        """
        patterns = self._extract_patterns(iteration)
        if not patterns:
            return []

        entries = self._load()
        for pattern in patterns:
            entries.append(
                {
                    "category": pattern.category,
                    "pattern": pattern.pattern,
                    "iteration": pattern.iteration,
                    "timestamp": pattern.timestamp,
                }
            )
        self._save(entries)
        return patterns

    def summarize(self, limit: int = SUMMARY_LIMIT) -> str:
        """Return a concise, ranked summary of recent failure patterns.

        Empty string means no patterns have been recorded.
        """
        entries = self._load()
        if not entries:
            return ""
        counts = Counter(e["pattern"] for e in entries)
        top = counts.most_common(limit)
        lines = [f"- {pattern} (x{count})" for pattern, count in top]
        return "\n".join(lines)

    def clear(self) -> None:
        """Drop all recorded patterns. Useful after a strategic context reset."""
        if self.memory_path.is_file():
            self.memory_path.write_text("", encoding="utf-8")


# RACT 0.1.1 - Trust and tooling
