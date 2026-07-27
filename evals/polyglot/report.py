"""Aider Polyglot subset report — module_07 (v0.4.0).

Aggregates per-provider pass rate across the pinned subset and writes
both a machine-readable JSON and a human-readable Markdown summary
under ``evals/runs/<date>-polyglot-<provider>.{json,md}``.

The report is the source the leaderboard update script reads (see
``evals/leaderboard/update.py``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from evals.polyglot.runner import PolyglotResult


@dataclass
class PolyglotReport:
    """Aggregated per-provider report for the Polyglot subset."""

    provider: str
    subset_size: int
    passed_count: int
    failed_count: int
    skipped_count: int
    results: list[dict[str, Any]] = field(default_factory=list)
    generated_on: str = field(default_factory=lambda: date.today().isoformat())

    @property
    def pass_rate(self) -> float:
        scored = self.passed_count + self.failed_count
        return round(self.passed_count / scored, 4) if scored else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "corpus": "aider_polyglot",
            "provider": self.provider,
            "subset_size": self.subset_size,
            "passed": self.passed_count,
            "failed": self.failed_count,
            "skipped": self.skipped_count,
            "pass_rate": self.pass_rate,
            "generated_on": self.generated_on,
            "results": self.results,
        }


def build_report(provider: str, results: list[PolyglotResult]) -> PolyglotReport:
    """Aggregate a list of ``PolyglotResult`` into a ``PolyglotReport``."""
    passed = sum(1 for r in results if r.outcome == "passed")
    failed = sum(1 for r in results if r.outcome == "failed")
    skipped = sum(1 for r in results if r.outcome == "skipped")
    result_records: list[dict[str, Any]] = []
    for r in results:
        result_records.append(
            {
                "problem_id": r.problem_id,
                "outcome": r.outcome,
                "attempts": len(r.attempts),
                "skip_reason": r.skip_reason,
                "step_ids_hex": list(r.transaction_step_ids_hex),
            }
        )
    return PolyglotReport(
        provider=provider,
        subset_size=len(results),
        passed_count=passed,
        failed_count=failed,
        skipped_count=skipped,
        results=result_records,
    )


def write_report(report: PolyglotReport, runs_root: Path) -> tuple[Path, Path]:
    """Write ``<date>-polyglot-<provider>.{json,md}`` under ``runs_root``.

    Returns ``(json_path, md_path)``. The Markdown file is human-facing
    and includes a per-problem status table.
    """
    runs_root = Path(runs_root)
    runs_root.mkdir(parents=True, exist_ok=True)
    stem = f"{report.generated_on}-polyglot-{report.provider}"
    json_path = runs_root / f"{stem}.json"
    md_path = runs_root / f"{stem}.md"
    json_path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    md_lines = [
        f"# Aider Polyglot subset — provider `{report.provider}`",
        "",
        f"- **Generated:** {report.generated_on}",
        f"- **Subset size:** {report.subset_size}",
        f"- **Pass rate (scored):** {report.pass_rate:.2%} "
        f"({report.passed_count}/{report.passed_count + report.failed_count})",
        f"- **Skipped:** {report.skipped_count}",
        "",
        "## Per-problem",
        "",
        "| Problem | Outcome | Attempts | Skip reason |",
        "| --- | --- | --- | --- |",
    ]
    for r in report.results:
        md_lines.append(
            f"| `{r['problem_id']}` | {r['outcome']} | {r['attempts']} | "
            f"{r['skip_reason'] or '-'} |"
        )
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return json_path, md_path


# RACT 0.4.0
