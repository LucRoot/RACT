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
    floor_breached: bool = False

    def __str__(self) -> str:
        direction = "+" if self.percent_delta >= 0 else ""
        floor = " (floor breached)" if self.floor_breached else ""
        return (
            f"coverage delta: {direction}{self.percent_delta:.1f}%\n"
            f"  before: {self.before}\n"
            f"  after:  {self.after}\n"
            f"  verdict: {self.verdict}{floor}\n"
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


def compute_delta(
    before: CoverageSnapshot,
    after: CoverageSnapshot,
    *,
    min_percent: float | None = None,
) -> CoverageDelta:
    """Return the delta and a verdict.

    Verdict rules:
    - ``regress``: coverage percent dropped, or the after snapshot falls below
      an optional ``min_percent`` floor.
    - ``stagnant``: coverage unchanged and new missing lines exist.
    - ``earn``: coverage improved or held steady with no new missing lines and
      the after snapshot meets the optional floor.
    """
    percent_delta = after.percent_covered - before.percent_covered
    raw_line_delta = after.missing_lines - before.missing_lines
    floor_breached = False

    if min_percent is not None and after.percent_covered < min_percent:
        floor_breached = True
        verdict = "regress"
        detail = (
            f"coverage below {min_percent:.1f}% floor ({after.percent_covered:.1f}%)"
        )
    elif percent_delta < -0.01:
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
        floor_breached=floor_breached,
    )


BASELINE_FILE = ".rootact/coverage_baseline.json"


def _baseline_path(project_dir: Path) -> Path:
    return project_dir / BASELINE_FILE


def save_baseline(project_dir: Path | str, snapshot: CoverageSnapshot) -> Path:
    """Persist *snapshot* as the coverage baseline for the project."""
    project_dir = Path(project_dir)
    path = _baseline_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "percent_covered": snapshot.percent_covered,
        "covered_lines": snapshot.covered_lines,
        "missing_lines": snapshot.missing_lines,
        "total_lines": snapshot.total_lines,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_baseline(project_dir: Path | str) -> CoverageSnapshot | None:
    """Load the persisted baseline, or None if it has not been established."""
    path = _baseline_path(Path(project_dir))
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    try:
        return CoverageSnapshot(
            percent_covered=float(data["percent_covered"]),
            covered_lines=int(data["covered_lines"]),
            missing_lines=int(data["missing_lines"]),
            total_lines=int(data["total_lines"]),
        )
    except (KeyError, ValueError, TypeError):
        return None


def gate(
    project_dir: Path | str,
    *,
    pytest_args: list[str] | None = None,
    timeout: float = 300.0,
    update_baseline: bool = False,
    min_percent: float | None = None,
) -> Rooted[CoverageDelta]:
    """Run a coverage snapshot and compare it to the stored baseline.

    On the first call for a project, no baseline exists, so the current
    snapshot is stored and the verdict is ``"baseline"`` unless it sits below
    the optional ``min_percent`` floor, in which case the verdict is
    ``"regress"`` with ``floor_breached=True``. Subsequent calls compare
    against the stored baseline.
    """
    project_dir = Path(project_dir)
    after_rooted = run_snapshot(project_dir, pytest_args=pytest_args, timeout=timeout)
    if not after_rooted.is_ok():
        return Rooted(
            value=None,
            assumption=after_rooted.assumption,
            confidence=after_rooted.confidence,
            provenance=[*(after_rooted.provenance or []), "coverage_delta.gate"],
            error=after_rooted.error,
        )

    after = after_rooted.unwrap()
    before = load_baseline(project_dir)
    if before is None:
        save_baseline(project_dir, after)
        if min_percent is not None and after.percent_covered < min_percent:
            delta = CoverageDelta(
                before=after,
                after=after,
                percent_delta=0.0,
                verdict="regress",
                detail=f"baseline below {min_percent:.1f}% floor ({after.percent_covered:.1f}%)",
                floor_breached=True,
            )
        else:
            delta = CoverageDelta(
                before=after,
                after=after,
                percent_delta=0.0,
                verdict="baseline",
                detail="baseline established; no prior snapshot found",
            )
        return Rooted(
            value=delta,
            assumption="No coverage baseline found; stored current snapshot as baseline.",
            confidence=1.0,
            provenance=["coverage_delta.gate"],
        )

    delta = compute_delta(before, after, min_percent=min_percent)
    if update_baseline:
        save_baseline(project_dir, after)

    return Rooted(
        value=delta,
        assumption="Coverage snapshot compared against stored baseline.",
        confidence=1.0,
        provenance=["coverage_delta.gate"],
    )


# RACT 0.1.0 - Initial Public Release
