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
from dataclasses import dataclass, field
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
    per_file: dict[str, "CoverageSnapshot"] | None = None

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
    per_file_breaches: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        direction = "+" if self.percent_delta >= 0 else ""
        floor = " (floor breached)" if self.floor_breached else ""
        breaches = ""
        if self.per_file_breaches:
            breaches = "\n  per-file breaches: " + ", ".join(self.per_file_breaches)
        return (
            f"coverage delta: {direction}{self.percent_delta:.1f}%\n"
            f"  before: {self.before}\n"
            f"  after:  {self.after}\n"
            f"  verdict: {self.verdict}{floor}\n"
            f"  detail: {self.detail}{breaches}"
        )


def _parse_coverage_json(data: dict[str, Any]) -> CoverageSnapshot | None:
    """Return a snapshot from a pytest-cov JSON report, or None if malformed."""
    totals = data.get("totals", {})
    percent = totals.get("percent_covered")
    if percent is None:
        return None
    per_file: dict[str, CoverageSnapshot] | None = None
    files = data.get("files")
    if isinstance(files, dict):
        per_file = {}
        for raw_path, fdata in files.items():
            key = str(raw_path).replace("\\", "/")
            summary = fdata.get("summary", {}) if isinstance(fdata, dict) else {}
            f_percent = summary.get("percent_covered")
            if f_percent is None:
                continue
            per_file[key] = CoverageSnapshot(
                percent_covered=float(f_percent),
                covered_lines=int(summary.get("covered_lines", 0)),
                missing_lines=int(summary.get("missing_lines", 0)),
                total_lines=int(summary.get("num_statements", 0)),
            )
        if not per_file:
            per_file = None
    return CoverageSnapshot(
        percent_covered=float(percent),
        covered_lines=int(totals.get("covered_lines", 0)),
        missing_lines=int(totals.get("missing_lines", 0)),
        total_lines=int(totals.get("num_statements", 0)),
        per_file=per_file,
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


def _check_per_file_floors(
    snapshot: CoverageSnapshot,
    floors: dict[str, float],
) -> list[str]:
    """Return a list of files whose coverage sits below the configured floor."""
    if not floors or snapshot.per_file is None:
        return []
    breaches: list[str] = []
    for pattern, floor in floors.items():
        key = pattern.replace("\\", "/")
        file_snapshot = snapshot.per_file.get(key)
        if file_snapshot is None:
            # A configured floor for a missing file is a breach: the file no
            # longer exists or was not measured.
            breaches.append(f"{key}: missing (floor {floor:.1f}%)")
            continue
        if file_snapshot.percent_covered < floor:
            breaches.append(
                f"{key}: {file_snapshot.percent_covered:.1f}% < {floor:.1f}%"
            )
    return breaches


def _coverage_color(percent: float) -> str:
    """Return a shields.io color name for a coverage percentage."""
    if percent >= 90:
        return "brightgreen"
    if percent >= 80:
        return "green"
    if percent >= 70:
        return "yellowgreen"
    if percent >= 60:
        return "yellow"
    if percent >= 50:
        return "orange"
    return "red"


def save_coverage_badge(
    snapshot: CoverageSnapshot,
    badge_path: Path | str,
) -> Path:
    """Write a Shields endpoint badge describing *snapshot*."""
    badge_path = Path(badge_path)
    badge_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "label": "coverage",
        "message": f"{snapshot.percent_covered:.1f}%",
        "color": _coverage_color(snapshot.percent_covered),
    }
    badge_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return badge_path


BASELINE_FILE = ".rootact/coverage_baseline.json"


def _baseline_path(project_dir: Path) -> Path:
    return project_dir / BASELINE_FILE


def _snapshot_to_dict(snapshot: CoverageSnapshot) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "percent_covered": snapshot.percent_covered,
        "covered_lines": snapshot.covered_lines,
        "missing_lines": snapshot.missing_lines,
        "total_lines": snapshot.total_lines,
    }
    if snapshot.per_file:
        payload["per_file"] = {
            path: {
                "percent_covered": snap.percent_covered,
                "covered_lines": snap.covered_lines,
                "missing_lines": snap.missing_lines,
                "total_lines": snap.total_lines,
            }
            for path, snap in snapshot.per_file.items()
        }
    return payload


def _dict_to_snapshot(data: dict[str, Any]) -> CoverageSnapshot | None:
    try:
        per_file_data = data.get("per_file")
        per_file: dict[str, CoverageSnapshot] | None = None
        if isinstance(per_file_data, dict):
            per_file = {}
            for path, snap in per_file_data.items():
                if not isinstance(snap, dict):
                    continue
                per_file[path] = CoverageSnapshot(
                    percent_covered=float(snap["percent_covered"]),
                    covered_lines=int(snap["covered_lines"]),
                    missing_lines=int(snap["missing_lines"]),
                    total_lines=int(snap["total_lines"]),
                )
            if not per_file:
                per_file = None
        return CoverageSnapshot(
            percent_covered=float(data["percent_covered"]),
            covered_lines=int(data["covered_lines"]),
            missing_lines=int(data["missing_lines"]),
            total_lines=int(data["total_lines"]),
            per_file=per_file,
        )
    except (KeyError, ValueError, TypeError):
        return None


def save_baseline(project_dir: Path | str, snapshot: CoverageSnapshot) -> Path:
    """Persist *snapshot* as the coverage baseline for the project."""
    project_dir = Path(project_dir)
    path = _baseline_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_snapshot_to_dict(snapshot), indent=2),
        encoding="utf-8",
    )
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
    return _dict_to_snapshot(data)


def gate(
    project_dir: Path | str,
    *,
    pytest_args: list[str] | None = None,
    timeout: float = 300.0,
    update_baseline: bool = False,
    min_percent: float | None = None,
    per_file_min_percent: dict[str, float] | None = None,
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
    per_file_breaches = _check_per_file_floors(after, per_file_min_percent or {})
    before = load_baseline(project_dir)
    if before is None:
        save_baseline(project_dir, after)
        if per_file_breaches:
            delta = CoverageDelta(
                before=after,
                after=after,
                percent_delta=0.0,
                verdict="regress",
                detail="baseline established; per-file floor(s) breached",
                per_file_breaches=per_file_breaches,
            )
        elif min_percent is not None and after.percent_covered < min_percent:
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
    if per_file_breaches:
        # Promote to regress when any configured per-file floor is breached,
        # regardless of aggregate movement.
        delta = CoverageDelta(
            before=delta.before,
            after=delta.after,
            percent_delta=delta.percent_delta,
            verdict="regress",
            detail=f"{delta.detail}; per-file floor(s) breached",
            floor_breached=delta.floor_breached,
            per_file_breaches=per_file_breaches,
        )
    if update_baseline:
        save_baseline(project_dir, after)

    return Rooted(
        value=delta,
        assumption="Coverage snapshot compared against stored baseline.",
        confidence=1.0,
        provenance=["coverage_delta.gate"],
    )


# RACT 0.1.1 - Trust and tooling
