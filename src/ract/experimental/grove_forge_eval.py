# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Grove Forge benchmark auto-evaluation and learning-feed hook.

Reads Grove Forge benchmark result JSON files, extracts pass-rate and latency
metrics, and appends structured learnings to the learning feed so benchmark
failures and regressions become training signal for the council.
"""

import datetime
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple


DEFAULT_LEARNING_FEED_PATHS = [
    Path("C:/RootClaw/data/ract/learning_feed.jsonl"),
    Path(".ract/learning_feed.jsonl"),
]


@dataclass
class BatterySummary:
    """Aggregated metrics for one Grove Forge battery/stack result."""

    battery: str = ""
    stack: str = ""
    n_problems: int = 0
    n_passed: int = 0
    n_errored: int = 0
    n_skipped: int = 0
    pass_rate: float = 0.0
    wall_clock_s: float = 0.0
    mean_wall_s: float = 0.0
    p50_wall_s: float = 0.0
    p95_wall_s: float = 0.0


@dataclass
class EvalReport:
    """Summary of all benchmark results found in a directory."""

    result_files: List[Path] = field(default_factory=list)
    batteries: List[BatterySummary] = field(default_factory=list)
    aggregate_pass_rate: float = 0.0
    total_problems: int = 0
    total_passed: int = 0
    errors: List[str] = field(default_factory=list)


def _percentile(values: List[float], pct: float) -> float:
    """Return the ``pct`` percentile of ``values`` using nearest-rank."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(math.ceil(pct / 100.0 * len(sorted_vals))) - 1
    return sorted_vals[max(0, idx)]


def _summarize_battery(data: Dict[str, Any], source: Path) -> BatterySummary:
    """Convert a Grove Forge result dict into a ``BatterySummary``."""
    per_problem = data.get("per_problem") or []
    wall_times = [
        float(p.get("wall_s", 0.0))
        for p in per_problem
        if isinstance(p, dict) and "wall_s" in p
    ]
    mean_wall = sum(wall_times) / len(wall_times) if wall_times else 0.0
    return BatterySummary(
        battery=str(data.get("battery", source.stem)),
        stack=str(data.get("stack", "unknown")),
        n_problems=int(data.get("n_problems", 0)),
        n_passed=int(data.get("n_passed", 0)),
        n_errored=int(data.get("n_errored", 0)),
        n_skipped=int(data.get("n_skipped", 0)),
        pass_rate=float(data.get("pass_rate", 0.0)),
        wall_clock_s=float(data.get("wall_clock_s", 0.0)),
        mean_wall_s=round(mean_wall, 3),
        p50_wall_s=round(_percentile(wall_times, 50), 3),
        p95_wall_s=round(_percentile(wall_times, 95), 3),
    )


def _load_result(path: Path) -> Tuple[Dict[str, Any], str]:
    """Load a single Grove Forge result JSON file.

    Returns ``(data, error_message)``. ``data`` is empty if loading failed.
    """
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (json.JSONDecodeError, OSError) as exc:
        return {}, f"failed to load {path}: {exc}"
    if not isinstance(data, dict):
        return {}, f"unexpected top-level type in {path}: {type(data).__name__}"
    return data, ""


def evaluate_results(results_dir: Path, recursive: bool = True) -> EvalReport:
    """Scan ``results_dir`` for Grove Forge result JSON files and summarize them.

    Files are matched by ``*.json`` extension. A file is considered a result if
    it contains ``battery`` and ``n_problems`` keys. Malformed files are recorded
    in ``report.errors`` but do not abort the scan.
    """
    report = EvalReport()
    if not results_dir.is_dir():
        report.errors.append(f"results directory not found: {results_dir}")
        return report

    glob = results_dir.rglob("*.json") if recursive else results_dir.glob("*.json")
    for path in sorted(glob):
        data, error = _load_result(path)
        if error:
            report.errors.append(error)
            continue
        if "battery" not in data or "n_problems" not in data:
            # Skip non-benchmark JSON files quietly.
            continue
        report.result_files.append(path)
        report.batteries.append(_summarize_battery(data, path))

    total_problems = sum(b.n_problems for b in report.batteries)
    total_passed = sum(b.n_passed for b in report.batteries)
    report.total_problems = total_problems
    report.total_passed = total_passed
    report.aggregate_pass_rate = (
        total_passed / total_problems if total_problems else 0.0
    )
    return report


def _learning_entry(report: EvalReport, source_dir: Path) -> Dict[str, Any]:
    """Build a learning-feed entry from an eval report."""
    battery_names = sorted({f"{b.battery}/{b.stack}" for b in report.batteries})
    battery_summary = ", ".join(battery_names) if battery_names else "none"
    return {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "type": "ract_training",
        "source": "grove-forge-benchmark-auto-eval",
        "finding": (
            f"Grove Forge auto-eval scanned {len(report.result_files)} result file(s) "
            f"from {source_dir}. Batteries: {battery_summary}. "
            f"Aggregate pass rate: {report.aggregate_pass_rate:.2%} "
            f"({report.total_passed}/{report.total_problems})."
        ),
        "action": "Battery summaries appended; review failures for model/stack regressions.",
        "batteries": [
            {
                "battery": b.battery,
                "stack": b.stack,
                "n_problems": b.n_problems,
                "n_passed": b.n_passed,
                "pass_rate": b.pass_rate,
                "wall_clock_s": b.wall_clock_s,
                "mean_wall_s": b.mean_wall_s,
                "p95_wall_s": b.p95_wall_s,
            }
            for b in report.batteries
        ],
        "errors": report.errors,
    }


def append_to_learning_feed(
    report: EvalReport,
    results_dir: Path,
    feed_paths: List[Path] | None = None,
) -> List[Path]:
    """Append a learning entry to each configured feed path.

    Missing parent directories are created. Files that cannot be written are
    silently skipped so that a missing secondary path does not break the primary
    feed update.
    """
    paths = feed_paths or DEFAULT_LEARNING_FEED_PATHS
    entry = _learning_entry(report, results_dir)
    line = json.dumps(entry, ensure_ascii=False)
    written: List[Path] = []
    for path in paths:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            written.append(path)
        except OSError:
            continue
    return written


def report_to_dict(report: EvalReport) -> Dict[str, Any]:
    """Convert an ``EvalReport`` to a JSON-serializable dict."""
    return {
        "result_files": [str(p) for p in report.result_files],
        "batteries": [b.__dict__ for b in report.batteries],
        "aggregate_pass_rate": report.aggregate_pass_rate,
        "total_problems": report.total_problems,
        "total_passed": report.total_passed,
        "errors": report.errors,
    }
