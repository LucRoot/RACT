# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from pathlib import Path

import pytest

from ract.experimental.grove_forge_eval import (
    BatterySummary,
    append_to_learning_feed,
    evaluate_results,
    report_to_dict,
)


def _battery_result(
    battery: str = "humaneval",
    stack: str = "base",
    n_problems: int = 5,
    n_passed: int = 2,
    wall_clock_s: float = 100.0,
    per_problem: list | None = None,
) -> dict:
    return {
        "battery": battery,
        "stack": stack,
        "n_problems": n_problems,
        "n_passed": n_passed,
        "n_errored": 0,
        "n_skipped": 0,
        "pass_rate": n_passed / n_problems if n_problems else 0.0,
        "wall_clock_s": wall_clock_s,
        "per_problem": per_problem
        or [{"wall_s": 10.0, "passed": i < n_passed} for i in range(n_problems)],
    }


def test_evaluate_results_finds_and_summarizes_batteries(tmp_path: Path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "humaneval_base.json").write_text(
        json.dumps(_battery_result("humaneval", "base", 5, 2)), encoding="utf-8"
    )
    (results_dir / "mbpp_base.json").write_text(
        json.dumps(_battery_result("mbpp", "base", 4, 1)), encoding="utf-8"
    )

    report = evaluate_results(results_dir)
    assert len(report.result_files) == 2
    assert len(report.batteries) == 2
    assert report.total_problems == 9
    assert report.total_passed == 3
    assert report.aggregate_pass_rate == pytest.approx(3 / 9)


def test_evaluate_results_skips_non_benchmark_json(tmp_path: Path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "config.json").write_text(
        json.dumps({"model": "qwen"}), encoding="utf-8"
    )
    (results_dir / "humaneval_base.json").write_text(
        json.dumps(_battery_result()), encoding="utf-8"
    )

    report = evaluate_results(results_dir)
    assert len(report.result_files) == 1
    assert report.batteries[0].battery == "humaneval"


def test_evaluate_results_recursive(tmp_path: Path):
    results_dir = tmp_path / "results"
    nested = results_dir / "cycle_9"
    nested.mkdir(parents=True)
    (nested / "humaneval.json").write_text(
        json.dumps(_battery_result()), encoding="utf-8"
    )

    report = evaluate_results(results_dir, recursive=True)
    assert len(report.result_files) == 1

    report_flat = evaluate_results(results_dir, recursive=False)
    assert len(report_flat.result_files) == 0


def test_evaluate_results_missing_directory(tmp_path: Path):
    report = evaluate_results(tmp_path / "missing")
    assert report.errors
    assert "not found" in report.errors[0]


def test_evaluate_results_bad_json_recorded(tmp_path: Path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "bad.json").write_text("not json", encoding="utf-8")

    report = evaluate_results(results_dir)
    assert len(report.errors) == 1
    assert "bad.json" in report.errors[0]


def test_battery_summary_percentiles():
    data = _battery_result(per_problem=[{"wall_s": float(i)} for i in range(1, 11)])
    summary = BatterySummary(
        **{
            k: data.get(k, 0)
            for k in [
                "battery",
                "stack",
                "n_problems",
                "n_passed",
                "n_errored",
                "n_skipped",
                "pass_rate",
                "wall_clock_s",
            ]
        }
    )
    assert summary.battery == "humaneval"
    assert summary.n_problems == 5


def test_append_to_learning_feed_writes_entry(tmp_path: Path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "humaneval_base.json").write_text(
        json.dumps(_battery_result()), encoding="utf-8"
    )
    feed_path = tmp_path / "learning_feed.jsonl"
    report = evaluate_results(results_dir)

    written = append_to_learning_feed(report, results_dir, feed_paths=[feed_path])
    assert written == [feed_path]

    lines = feed_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["type"] == "ract_training"
    assert entry["source"] == "grove-forge-benchmark-auto-eval"
    assert "humaneval" in entry["finding"]


def test_report_to_dict_serializable(tmp_path: Path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "humaneval_base.json").write_text(
        json.dumps(_battery_result()), encoding="utf-8"
    )
    report = evaluate_results(results_dir)
    data = report_to_dict(report)
    assert data["total_problems"] == 5
    assert "batteries" in data
    assert isinstance(json.dumps(data), str)
