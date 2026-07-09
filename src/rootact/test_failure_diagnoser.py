# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Test failure diagnosis and repair intent generation.

When the loop's test suite fails, the TestFailureDiagnoser reads the pytest
output, extracts the failing cases, locates the relevant source files, and
composes a focused repair prompt. The goal is to give the management model
just enough context to fix the source (not the tests) on the next iteration.

LR:: This is the failure-repair path of the self-recursing loop. A loop that
stops at the first red test is not autonomous; a loop that asks the model to
diagnose and repair the failure is.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from rootact.rooted import Rooted


@dataclass(frozen=True)
class FailureCase:
    """One failing test extracted from pytest output."""

    test_file: str
    test_function: str
    source_file: str | None = None
    line_number: int | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class RepairIntent:
    """A structured request to repair failing tests."""

    summary: str
    failing_tests: list[str] = field(default_factory=list)
    relevant_files: list[str] = field(default_factory=list)
    prompt: str = ""


class TestFailureDiagnoser:
    """Parse pytest output and build a repair intent."""

    # Tell pytest not to collect this utility class as a test class.
    __test__ = False

    # Patterns for the short-summary line:
    #   tests/test_foo.py::test_name FAILED
    #   FAILED tests/test_foo.py::test_name - message
    _TEST_NODE_RE = re.compile(
        r"^(?:(?:FAILED|ERROR)\s+)?(?P<file>[\w/\\.-]+\.py)::(?P<func>[\w:]+)\s+(?:FAILED|ERROR|-)",
        re.MULTILINE,
    )

    # Traceback file/line marker: File "path/to/file.py", line 42
    _TRACEBACK_RE = re.compile(
        r'^File "(?P<file>[^"]+)", line (?P<line>\d+).*', re.MULTILINE
    )

    # Error type/message: ExceptionClass: message
    _ERROR_RE = re.compile(
        r"^(?P<type>[A-Za-z_][\w.]*Error|AssertionError):\s*(?P<msg>.*)$"
    )

    def __init__(
        self,
        project_dir: Path | str,
        *,
        python_executable: str = "python",
        test_command: list[str] | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.python_executable = python_executable
        self.test_command = list(test_command) if test_command else ["-m", "pytest"]

    def diagnose(self, pytest_output: str) -> Rooted[RepairIntent]:
        """Extract failures from ``pytest_output`` and build a repair intent."""
        failures = self._parse_failures(pytest_output)
        if not failures:
            return Rooted(
                value=None,
                assumption="Pytest output contains at least one identifiable failure.",
                confidence=0.0,
                provenance=["test_failure_diagnoser.diagnose"],
                error="No failing tests were parsed from pytest output.",
            )

        files = self._rank_files(failures)
        prompt = self._build_repair_prompt(failures, files)
        summary = f"{len(failures)} failing test(s); {len(files)} relevant file(s)"
        intent = RepairIntent(
            summary=summary,
            failing_tests=[f"{f.test_file}::{f.test_function}" for f in failures],
            relevant_files=files,
            prompt=prompt,
        )
        return Rooted(
            value=intent,
            assumption="Pytest failures can be localized to a small set of source files.",
            confidence=0.85,
            provenance=["test_failure_diagnoser.diagnose"],
        )

    def capture_with_traceback(
        self,
        extra_args: list[str] | None = None,
    ) -> tuple[int, str]:
        """Run pytest with a verbose traceback and return (returncode, output)."""
        args = [self.python_executable, *self.test_command, "-q", "--tb=long"]
        if extra_args:
            args.extend(extra_args)
        try:
            proc = subprocess.run(
                args,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return -1, "test runner unavailable or timed out"
        return proc.returncode, proc.stdout + proc.stderr

    def _parse_failures(self, output: str) -> list[FailureCase]:
        """Extract failing test nodes and any traceback details."""
        failures: list[FailureCase] = []

        # First pass: identify failing test nodes from the summary.
        for match in self._TEST_NODE_RE.finditer(output):
            test_file = match.group("file").replace("\\", "/")
            test_function = match.group("func")
            failures.append(
                FailureCase(
                    test_file=test_file,
                    test_function=test_function,
                )
            )

        # If no summary nodes, try to infer from failure headers.
        if not failures:
            failures = self._parse_failure_headers(output)

        # Enrich each failure with the nearest traceback and error message.
        enriched: list[FailureCase] = []
        for failure in failures:
            section = self._extract_failure_section(output, failure)
            source_file, line_number = self._nearest_traceback_source(section)
            error_type, error_message = self._extract_error_message(section)

            # If the only traceback frame is the test itself, infer the source
            # module from the test file's imports.
            if source_file is None or "tests" in source_file:
                inferred = self._infer_source_from_test(failure.test_file)
                if inferred is not None:
                    source_file = inferred
                    line_number = None

            enriched.append(
                FailureCase(
                    test_file=failure.test_file,
                    test_function=failure.test_function,
                    source_file=source_file,
                    line_number=line_number,
                    error_type=error_type,
                    error_message=error_message,
                )
            )

        return enriched

    def _parse_failure_headers(self, output: str) -> list[FailureCase]:
        """Fallback parser for failure lines like 'FAILED tests/foo.py::bar'."""
        failures: list[FailureCase] = []
        for line in output.splitlines():
            line = line.strip()
            if not line.startswith(("FAILED ", "ERROR ")):
                continue
            remainder = line.split(None, 1)[1] if " " in line else line
            if "::" not in remainder:
                continue
            file_part, func_part = remainder.split("::", 1)
            failures.append(
                FailureCase(
                    test_file=file_part.replace("\\", "/"),
                    test_function=func_part.split()[0]
                    if " " in func_part
                    else func_part,
                )
            )
        return failures

    def _extract_failure_section(self, output: str, failure: FailureCase) -> str:
        """Return the portion of output most likely associated with a failure."""
        back_slash_file = failure.test_file.replace("/", "\\")
        needles = [
            f"{failure.test_file}::{failure.test_function}",
            f"{back_slash_file}::{failure.test_function}",
        ]
        idx = -1
        for needle in needles:
            idx = output.find(needle)
            if idx != -1:
                break
        if idx == -1:
            return output
        # Slice a generous window around the match.
        start = max(0, idx - 500)
        end = min(len(output), idx + 4000)
        return output[start:end]

    def _nearest_traceback_source(self, section: str) -> tuple[str | None, int | None]:
        """Find the source file/line closest to the assertion in the traceback."""
        matches = list(self._TRACEBACK_RE.finditer(section))
        if not matches:
            return None, None
        # Prefer the last traceback frame that points inside the project.
        for match in reversed(matches):
            file_path = match.group("file")
            rel = self._relative_path(file_path)
            if rel is not None and "tests" not in rel:
                return rel, int(match.group("line"))
        # Fall back to the last frame overall.
        last = matches[-1]
        rel = self._relative_path(last.group("file"))
        return rel, int(last.group("line"))

    def _infer_source_from_test(self, test_file: str) -> str | None:
        """Read a test file and map its imports back to source files."""
        # Normalize separators so the same logic works on Windows and Unix.
        local_path = Path(test_file.replace("\\", "/"))
        path = self.project_dir / local_path
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        # Collect imported module names.
        modules: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("from "):
                parts = line.split()
                if len(parts) >= 2 and parts[1]:
                    modules.append(parts[1])
            elif line.startswith("import "):
                remainder = line[7:]
                for item in remainder.split(","):
                    modules.append(item.strip().split(" as ")[0])

        # Try to map modules to source files under the project directory.
        for module in modules:
            candidate = module.replace(".", "/") + ".py"
            rel_path = candidate
            if (self.project_dir / rel_path).is_file():
                return rel_path
        return None

    def _extract_error_message(self, section: str) -> tuple[str | None, str | None]:
        """Extract the final error type and message from a failure section."""
        for line in reversed(section.splitlines()):
            match = self._ERROR_RE.match(line.strip())
            if match:
                return match.group("type"), match.group("msg")
        return None, None

    def _rank_files(self, failures: list[FailureCase]) -> list[str]:
        """Rank source and test files by relevance to the failures."""
        scores: dict[str, float] = {}

        for failure in failures:
            test_file = self._relative_path(failure.test_file)
            if test_file is None:
                # The test file may already be relative to the project directory.
                candidate = failure.test_file.replace("\\", "/")
                if (self.project_dir / candidate).is_file():
                    test_file = candidate
            if test_file is not None:
                scores[test_file] = scores.get(test_file, 0.0) + 1.0

            source_file = failure.source_file
            if source_file is not None:
                scores[source_file] = scores.get(source_file, 0.0) + 2.0

        # Only return files that actually exist under the project directory.
        existing = {path for path in scores if (self.project_dir / path).is_file()}
        return sorted(
            existing,
            key=lambda p: (-scores[p], p),
        )

    def _build_repair_prompt(
        self, failures: list[FailureCase], files: list[str]
    ) -> str:
        """Compose a focused repair prompt for the management model."""
        lines: list[str] = [
            "The test suite is failing. Diagnose the root cause and repair the SOURCE code so all tests pass.",
            "",
            "Failing tests:",
        ]
        for failure in failures:
            node = f"{failure.test_file}::{failure.test_function}"
            detail = f"  - {node}"
            if failure.error_type:
                detail += f" -> {failure.error_type}"
                if failure.error_message:
                    detail += f": {failure.error_message}"
            if failure.source_file:
                detail += f" (source: {failure.source_file}"
                if failure.line_number:
                    detail += f":{failure.line_number}"
                detail += ")"
            lines.append(detail)

        lines.extend(["", "Relevant files (most important first):"])
        for path in files:
            lines.append(f"  - {path}")

        lines.extend(
            [
                "",
                "Instructions:",
                "  1. Read the failing tests and the relevant source files.",
                "  2. Identify whether the bug is in the source implementation or in a stale test expectation.",
                "  3. Modify the SOURCE code (or the test, if the source contract is intentionally correct).",
                "  4. Preserve the Root Knot signature markers (__root_author__, _ROOT_KNOT, __ract_name__) in any new or edited files.",
                "  5. Do not rename tests solely to make them pass.",
            ]
        )

        return "\n".join(lines)

    def _relative_path(self, path: str) -> str | None:
        """Return ``path`` relative to the project directory, or None if outside."""
        try:
            target = Path(path).resolve()
            rel = target.relative_to(self.project_dir.resolve())
            return str(rel).replace("\\", "/")
        except (ValueError, OSError):
            return None


# RACT 0.1.1 - Trust and Tooling
