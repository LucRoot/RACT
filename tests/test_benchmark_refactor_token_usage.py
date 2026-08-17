"""Smoke test for the refactor-token-usage benchmark.

Asserts the benchmark runs end-to-end and the RACT milestone-driven loop is
strictly better than the naive fixed-iteration baseline on the tokens-to-pass
dimension. This is the CI gate for the benchmark harness (v0.3 Module 4).

The benchmark is deterministic, so this test is stable; if it ever fails it
means either the harness regressed or the milestone-termination policy
stopped beating the naive baseline (both are real signals).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BENCH_DIR = (
    Path(__file__).resolve().parent.parent
    / "evals"
    / "benchmarks"
    / "refactor-token-usage"
)


def _load_report_module():
    """Load report.py by path (the bench dir uses hyphen, so not a package)."""
    sys.path.insert(0, str(BENCH_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "bench_report", BENCH_DIR / "report.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if str(BENCH_DIR) in sys.path:
            sys.path.remove(str(BENCH_DIR))


@pytest.fixture(scope="module")
def report_module():
    return _load_report_module()


def test_benchmark_contender_is_strictly_better(report_module) -> None:
    baseline = report_module.run_side(
        "naive-baseline", report_module.NaiveLoopRunner(5), runs=3
    )
    contender = report_module.run_side(
        "ract-contender", report_module.RACTLoopRunner(5), runs=3
    )
    assert contender["mean_tokens_to_pass"] < baseline["mean_tokens_to_pass"], (
        "RACT milestone-driven loop must spend fewer tokens to a passing state "
        f"than the naive baseline (got contender={contender['mean_tokens_to_pass']} "
        f"vs baseline={baseline['mean_tokens_to_pass']})"
    )
    # Both must actually reach a passing state; otherwise the comparison is void.
    assert contender["passed_runs"] == 3
    assert baseline["passed_runs"] == 3


def test_benchmark_report_files_exist() -> None:
    """The committed report artifacts must exist and parse."""
    json_path = BENCH_DIR / "report.json"
    md_path = BENCH_DIR / "report.md"
    assert json_path.is_file(), "benchmark report.json missing — run report.py"
    assert md_path.is_file(), "benchmark report.md missing — run report.py"
    import json

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["contender_strictly_better"] is True
    assert "refactor-function" in data["task"]


# RACT 0.3.0
