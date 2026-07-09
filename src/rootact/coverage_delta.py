# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Earned-coverage gate for RACT.

The harness can take a coverage snapshot before and after a run. If the
second snapshot shows lower coverage than the first, the run added
uncovered code and the gate fails. This replaces raw test-count vanity with
a measure of earned quality.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rootact.rooted import Rooted


@dataclass(frozen=True)
class CoverageSnapshot:
    """A single coverage measurement."""

    percent_covered: float
    covered_lines: int
    missing_lines: int
    total_lines: int

    def __str__(self) -> str:
        return (
            f"{self.percent_covered:.1f}% covered "
            f"({self.covered_lines}/{self.total_lines} lines; "
            f"{self.missing_lines} missing)"
        )


@dataclass(frozen=True)
class CoverageDelta:
    """Difference between two coverage snapshots."""

    before: CoverageSnapshot
    after: CoverageSnapshot
    percent_delta: float
    verdict: str
    detail: str

    def __str__(self) -> str:
        direction = "+" if self.percent_delta >= 0 else ""
        return (
            f"coverage delta: {direction}{self.percent_delta:.1f}%\n"
            f"  before: {self.before}\n"
            f"  after:  {self.after}\n"
            f"  verdict: {self.verdict}\n"
            f"  detail: {self.detail}"
        )


def _parse_coverage_json(data: dict[str, Any]) -> CoverageSnapshot | None:
    """Return a snapshot from a pytest-cov JSON report, or None if malformed."""
    totals = data.get("totals", {})
    percent = totals.get("percent_covered")
    if percent is None:
        return None
    return CoverageSnapshot(
        percent_covered=float(percent),
        covered_lines=int(totals.get("covered_lines", 0)),
        missing_lines=int(totals.get("missing_lines", 0)),
        total_lines=int(totals.get("num_statements", 0)),
    )


def read_snapshot(path: Path | str) -> Rooted[CoverageSnapshot]:
    """Load a snapshot from a pytest-cov ``coverage.json`` file."""
    path = Path(path)
    if not path.is_file():
        return Rooted(
            value=None,
            assumption=f"Coverage report exists: {path}",
            confidence=0.0,
            provenance=["coverage_delta.read_snapshot"],
            error=f"Coverage report not found: {path}",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Rooted(
            value=None,
            assumption=f"Coverage report is valid JSON: {path}",
            confidence=0.0,
            provenance=["coverage_delta.read_snapshot"],
            error=f"Failed to parse coverage report: {exc}",
        )
    snapshot = _parse_coverage_json(data)
    if snapshot is None:
        return Rooted(
            value=None,
            assumption="Coverage report contains pytest-cov totals.",
            confidence=0.0,
            provenance=["coverage_delta.read_snapshot"],
            error="Coverage report missing 'totals.percent_covered'.",
        )
    return Rooted(
        value=snapshot,
        assumption="Coverage report parsed successfully.",
        confidence=1.0,
        provenance=["coverage_delta.read_snapshot"],
    )


def run_snapshot(
    project_dir: Path | str,
    *,
    pytest_args: list[str] | None = None,
    timeout: float = 300.0,
) -> Rooted[CoverageSnapshot]:
    """Run pytest with JSON coverage and return a snapshot.

    This intentionally shells out to pytest rather than importing it, so the
    measurement reflects the same test runner the operator uses.
    """
    project_dir = Path(project_dir)
    args = list(pytest_args) if pytest_args else ["tests/", "-q"]
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *args,
        "--cov=rootact",
        "--cov-report=json",
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Rooted(
            value=None,
            assumption="pytest with coverage completes within timeout.",
            confidence=0.0,
            provenance=["coverage_delta.run_snapshot"],
            error="Coverage snapshot timed out.",
        )
    except FileNotFoundError:
        return Rooted(
            value=None,
            assumption="pytest is installed in the active environment.",
            confidence=0.0,
            provenance=["coverage_delta.run_snapshot"],
            error="pytest not found; cannot capture coverage snapshot.",
        )

    coverage_path = project_dir / "coverage.json"
    if not coverage_path.is_file():
        stdout = result.stdout[-500:] if result.stdout else ""
        stderr = result.stderr[-500:] if result.stderr else ""
        return Rooted(
            value=None,
            assumption="pytest produces coverage.json when invoked with --cov-report=json.",
            confidence=0.0,
            provenance=["coverage_delta.run_snapshot"],
            error=(
                f"coverage.json was not generated.\n"
                f"exit code: {result.returncode}\n"
                f"stdout tail: {stdout}\n"
                f"stderr tail: {stderr}"
            ),
        )

    return read_snapshot(coverage_path)


def compute_delta(before: CoverageSnapshot, after: CoverageSnapshot) -> CoverageDelta:
    """Return the delta and a verdict.

    Verdict rules:
    - ``regress``: coverage percent dropped.
    - ``stagnant``: coverage unchanged and new missing lines exist.
    - ``earn``: coverage improved or held steady with no new missing lines.
    """
    percent_delta = after.percent_covered - before.percent_covered
    raw_line_delta = after.missing_lines - before.missing_lines

    if percent_delta < -0.01:
        verdict = "regress"
        detail = "coverage dropped; new code is uncovered"
    elif abs(percent_delta) <= 0.01 and raw_line_delta > 0:
        verdict = "stagnant"
        detail = "coverage flat but missing lines increased"
    else:
        verdict = "earn"
        detail = "coverage held or improved"

    return CoverageDelta(
        before=before,
        after=after,
        percent_delta=percent_delta,
        verdict=verdict,
        detail=detail,
    )


def gate(
    project_dir: Path | str,
    *,
    pytest_args: list[str] | None = None,
    timeout: float = 300.0,
) -> Rooted[CoverageDelta]:
    """Run before/after snapshots and return the earned-coverage verdict."""
    before_rooted = run_snapshot(project_dir, pytest_args=pytest_args, timeout=timeout)
    if not before_rooted.is_ok():
        return before_rooted.with_step("coverage_delta.gate.before")

    after_rooted = run_snapshot(project_dir, pytest_args=pytest_args, timeout=timeout)
    if not after_rooted.is_ok():
        return after_rooted.with_step("coverage_delta.gate.after")

    delta = compute_delta(before_rooted.unwrap(), after_rooted.unwrap())
    return Rooted(
        value=delta,
        assumption="Coverage snapshots captured before and after execution.",
        confidence=1.0,
        provenance=["coverage_delta.gate"],
    )


# RACT 0.1.0 - Initial Public Release
