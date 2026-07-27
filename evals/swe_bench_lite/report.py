"""SWE-bench Lite report — module_07 (v0.4.0).

Aggregates per-provider pass rate across the pinned instance set and
writes both a machine-readable JSON and a human-readable Markdown
summary under
``evals/runs/<date>-swebench_lite-<provider>.{json,md}``. The report
is the source the leaderboard update script reads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from evals.swe_bench_lite.runner import SweBenchResult


@dataclass
class SweBenchReport:
    """Aggregated per-provider report for the SWE-bench Lite subset."""

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
            "corpus": "swebench_lite",
            "provider": self.provider,
            "subset_size": self.subset_size,
            "passed": self.passed_count,
            "failed": self.failed_count,
            "skipped": self.skipped_count,
            "pass_rate": self.pass_rate,
            "generated_on": self.generated_on,
            "results": self.results,
        }


def build_report(provider: str, results: list[SweBenchResult]) -> SweBenchReport:
    """Aggregate a list of ``SweBenchResult`` into a ``SweBenchReport``."""
    passed = sum(1 for r in results if r.outcome == "passed")
    failed = sum(1 for r in results if r.outcome == "failed")
    skipped = sum(1 for r in results if r.outcome == "skipped")
    result_records: list[dict[str, Any]] = []
    for r in results:
        result_records.append(
            {
                "instance_id": r.instance_id,
                "outcome": r.outcome,
                "fail_to_pass_ok": (
                    r.attempt.fail_to_pass_ok if r.attempt is not None else None
                ),
                "pass_to_pass_ok": (
                    r.attempt.pass_to_pass_ok if r.attempt is not None else None
                ),
                "skip_reason": r.skip_reason,
                "step_id_hex": r.transaction_step_id_hex,
            }
        )
    return SweBenchReport(
        provider=provider,
        subset_size=len(results),
        passed_count=passed,
        failed_count=failed,
        skipped_count=skipped,
        results=result_records,
    )


def write_report(report: SweBenchReport, runs_root: Path) -> tuple[Path, Path]:
    """Write ``<date>-swebench_lite-<provider>.{json,md}`` under ``runs_root``."""
    runs_root = Path(runs_root)
    runs_root.mkdir(parents=True, exist_ok=True)
    stem = f"{report.generated_on}-swebench_lite-{report.provider}"
    json_path = runs_root / f"{stem}.json"
    md_path = runs_root / f"{stem}.md"
    json_path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    md_lines = [
        f"# SWE-bench Lite — provider `{report.provider}`",
        "",
        f"- **Generated:** {report.generated_on}",
        f"- **Subset size:** {report.subset_size}",
        f"- **Pass rate (scored):** {report.pass_rate:.2%} "
        f"({report.passed_count}/{report.passed_count + report.failed_count})",
        f"- **Skipped:** {report.skipped_count}",
        "",
        "## Per-instance",
        "",
        "| Instance | Outcome | FAIL_TO_PASS | PASS_TO_PASS | Skip reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report.results:
        md_lines.append(
            f"| `{r['instance_id']}` | {r['outcome']} | "
            f"{r['fail_to_pass_ok']} | {r['pass_to_pass_ok']} | "
            f"{r['skip_reason'] or '-'} |"
        )
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return json_path, md_path


# RACT 0.4.0
