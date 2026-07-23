# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Lint and format repair driver for RACT.

Runs ruff check, ruff format --check, and mypy against a project, parses the
output, and builds a repair prompt so the self-recursing loop can fix static
analysis issues without operator intervention.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ract.rooted import Rooted


@dataclass
class LintIssue:
    """A single issue reported by a linter or formatter."""

    tool: str
    file: str
    line: int
    message: str


@dataclass
class LintReport:
    """Aggregate result of all configured lint/format checks."""

    issues: list[LintIssue]
    raw_output: str
    passed: bool


_RUFF_CHECK_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<message>.+)$"
)


class LintFormatRepair:
    """Execute lint/format checks and produce a repair prompt.

    LR:: The loop should not declare victory just because tests pass. ruff,
    ruff format, and mypy are the next line of defense. This driver makes them
    actionable inside the recursion.
    """

    def __init__(
        self,
        project_dir: Path,
        python_executable: str = "python",
        paths: list[str] | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.python_executable = python_executable
        self.paths = paths or ["src", "tests", "scripts"]

    def _collect_python_files(self) -> list[Path]:
        """Return all Python files under the configured paths."""
        files: list[Path] = []
        for path_str in self.paths:
            path = self.project_dir / path_str
            if not path.exists():
                continue
            if path.is_file() and path.suffix == ".py":
                files.append(path)
            elif path.is_dir():
                files.extend(
                    p for p in path.rglob("*.py") if "__pycache__" not in p.parts
                )
        return files

    def check(self) -> LintReport:
        """Run all configured checks and return a unified report."""
        issues: list[LintIssue] = []
        outputs: list[str] = []
        passed = True

        python_files = self._collect_python_files()
        if not python_files:
            return LintReport(issues=[], raw_output="", passed=True)

        for tool, args in [
            (
                "ruff-check",
                [self.python_executable, "-m", "ruff", "check", *self.paths],
            ),
            (
                "ruff-format",
                [
                    self.python_executable,
                    "-m",
                    "ruff",
                    "format",
                    "--check",
                    *self.paths,
                ],
            ),
            ("mypy", [self.python_executable, "-m", "mypy", *self.paths]),
        ]:
            try:
                proc = subprocess.run(
                    args,
                    cwd=self.project_dir,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                outputs.append(f"{tool}: unavailable or timed out")
                passed = False
                issues.append(
                    LintIssue(tool=tool, file="", line=0, message="tool unavailable")
                )
                continue

            output = (proc.stdout or "") + (proc.stderr or "")
            outputs.append(f"--- {tool} ---\n{output}")
            if proc.returncode != 0:
                passed = False
                issues.extend(self._parse_output(tool, output))

        return LintReport(
            issues=issues,
            raw_output="\n\n".join(outputs),
            passed=passed,
        )

    def _parse_output(self, tool: str, output: str) -> list[LintIssue]:
        """Parse tool output into LintIssue objects.

        Handles ruff and mypy line-oriented output. Unknown formats are folded
        into a single issue so nothing is silently dropped.
        """
        issues: list[LintIssue] = []
        parsed_any = False
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            issue = self._parse_line(tool, stripped)
            if issue is not None:
                issues.append(issue)
                parsed_any = True
        if not parsed_any and output.strip():
            issues.append(
                LintIssue(tool=tool, file="", line=0, message=output.strip()[:500])
            )
        return issues

    def _parse_line(self, tool: str, line: str) -> LintIssue | None:
        """Parse a single output line."""
        # Skip ruff multi-line visual noise.
        if line.startswith(("|", "-->", "help:", "Found", "[*]")):
            return None

        if tool == "ruff-check":
            # Format: file:line:col: CODE message
            match = _RUFF_CHECK_RE.match(line)
            if match:
                return LintIssue(
                    tool=tool,
                    file=match.group("file").strip(),
                    line=int(match.group("line")),
                    message=match.group("message").strip(),
                )
            return None

        if tool == "ruff-format":
            # Format: Would reformat: path
            if line.startswith("Would reformat:"):
                file_part = line[len("Would reformat:") :].strip()
                if file_part:
                    return LintIssue(
                        tool=tool, file=file_part, line=0, message="needs formatting"
                    )
            return None

        if tool == "mypy":
            # Format: file:line: severity: message  [code]
            if ":" not in line:
                return None
            parts = line.split(":", 2)
            if len(parts) < 3:
                return None
            try:
                file_part = parts[0].strip()
                line_no = int(parts[1].strip())
                message = parts[2].strip()
            except ValueError:
                return None
            if not file_part or not message:
                return None
            return LintIssue(tool=tool, file=file_part, line=line_no, message=message)
        return None

    def build_repair_prompt(self, report: LintReport) -> Rooted[dict[str, Any]]:
        """Return a Rooted repair prompt from a non-passing report."""
        if report.passed:
            return Rooted(
                value=None,
                assumption="Lint/format report has issues to repair.",
                confidence=0.0,
                provenance=["lint_format_repair.build_repair_prompt"],
                error="No lint/format issues to repair.",
            )

        lines: list[str] = [
            "Fix the following lint, format, and type-check issues. "
            "Apply the minimal changes needed to make all checks pass.",
            "",
            "Issues:",
        ]
        for issue in report.issues[:30]:
            loc = f"{issue.file}:{issue.line}" if issue.file else issue.tool
            lines.append(f"- {loc}: {issue.message}")
        if len(report.issues) > 30:
            lines.append(f"- ... and {len(report.issues) - 30} more issues")
        lines.extend(["", "Raw output:", report.raw_output[:2000]])

        return Rooted(
            value={
                "summary": f"{len(report.issues)} lint/format/type issues",
                "prompt": "\n".join(lines),
            },
            assumption="The repair prompt is grounded in actual tool output.",
            confidence=1.0,
            provenance=["lint_format_repair.build_repair_prompt"],
        )


# RACT 0.1.1 - Trust and tooling
