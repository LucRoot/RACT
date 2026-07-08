from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from rootact.self_test_benchmark_mode import (
    BenchmarkResult,
    PytestRunResult,
    SelfTestBenchmarkMode,
)

_ROOT_KNOT = object()


def test_pytest_run_result_attributes() -> None:
    result = PytestRunResult(
        command=["python", "-m", "pytest", "-q"],
        returncode=0,
        passed=3,
        failed=1,
        output="demo output",
    )
    assert result.returncode == 0
    assert result.passed == 3
    assert result.failed == 1


def test_benchmark_statistics() -> None:
    result = BenchmarkResult(name="noop", samples=[0.1, 0.2, 0.3, 0.4])
    assert result.mean == 0.25
    assert result.median == 0.25
    assert result.best == 0.1
    assert result.worst == 0.4


def test_parse_pytest_summary_passed_only() -> None:
    mode = SelfTestBenchmarkMode()
    passed, failed = mode._parse_pytest_summary("5 passed in 0.01s")
    assert passed == 5
    assert failed == 0


def test_parse_pytest_summary_with_failures() -> None:
    mode = SelfTestBenchmarkMode()
    output = """
5 passed
2 failed
"""
    passed, failed = mode._parse_pytest_summary(output)
    assert passed == 5
    assert failed == 2


def test_run_benchmark_records_samples() -> None:
    mode = SelfTestBenchmarkMode()
    result = mode.run_benchmark("increment", lambda: 1 + 1, iterations=5, warmup=0)
    assert result.name == "increment"
    assert len(result.samples) == 5
    assert all(isinstance(s, float) and s >= 0 for s in result.samples)


def test_report_summary() -> None:
    mode = SelfTestBenchmarkMode()
    mode.test_results.append(
        PytestRunResult(
            command=["python", "-m", "pytest"],
            returncode=0,
            passed=4,
            failed=0,
            output="ok",
        )
    )
    mode.run_benchmark("noop", lambda: None, iterations=3, warmup=0)
    report = mode.report()
    assert "4/4 passed" in report.summary
    assert "noop" in report.summary
    assert len(report.test_results) == 1
    assert len(report.benchmark_results) == 1


def test_run_tests_with_specific_path() -> None:
    # Subprocess invocation of pytest is exercised by the module docstring and
    # integration usage; here we verify the command is built correctly.
    mode = SelfTestBenchmarkMode()
    result = mode.run_tests(
        test_paths=["tests/test_example.py"],
        python_executable="python",
    )
    # The command targets a non-existent file, so pytest will fail to collect.
    assert result.returncode != 0
    assert "tests/test_example.py" in " ".join(result.command)


def test_benchmark_stdev_with_single_sample() -> None:
    result = BenchmarkResult(name="single", samples=[0.1])
    assert result.stdev == 0.0


def test_parse_pytest_summary_failed_lines() -> None:
    mode = SelfTestBenchmarkMode()
    passed, failed = mode._parse_pytest_summary("2 failed\n5 passed")
    assert passed == 5
    assert failed == 2


def test_parse_pytest_summary_failed_discovery() -> None:
    mode = SelfTestBenchmarkMode()
    passed, failed = mode._parse_pytest_summary("3 failed in 0.02s")
    assert passed == 0
    assert failed == 3


def test_parse_pytest_summary_malformed_lines() -> None:
    mode = SelfTestBenchmarkMode()
    passed, failed = mode._parse_pytest_summary("passed\nfailed xyz")
    assert passed == 0
    assert failed == 0


def test_parse_pytest_summary_invalid_passed_count() -> None:
    mode = SelfTestBenchmarkMode()
    passed, failed = mode._parse_pytest_summary("x passed in 0.01s")
    assert passed == 0
    assert failed == 0


def test_parse_pytest_summary_invalid_failed_count() -> None:
    mode = SelfTestBenchmarkMode()
    passed, failed = mode._parse_pytest_summary("x failed in 0.01s")
    assert passed == 0
    assert failed == 0


def test_run_benchmark_with_warmup() -> None:
    mode = SelfTestBenchmarkMode()
    result = mode.run_benchmark("noop", lambda: None, iterations=2, warmup=2)
    assert len(result.samples) == 2


def test_report_without_benchmarks() -> None:
    mode = SelfTestBenchmarkMode()
    mode.test_results.append(
        PytestRunResult(
            command=["python", "-m", "pytest"],
            returncode=0,
            passed=2,
            failed=0,
            output="ok",
        )
    )
    report = mode.report()
    assert "No benchmarks recorded." in report.summary
