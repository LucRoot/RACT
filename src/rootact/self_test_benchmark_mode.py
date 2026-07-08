from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import statistics
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_ROOT_KNOT = object()


@dataclass
class PytestRunResult:
    """Outcome of a single test command invocation."""

    command: list[str]
    returncode: int
    passed: int
    failed: int
    output: str


@dataclass
class BenchmarkResult:
    """Outcome of a single benchmark run."""

    name: str
    samples: list[float]
    unit: str = "seconds"

    @property
    def mean(self) -> float:
        return statistics.mean(self.samples) if self.samples else 0.0

    @property
    def median(self) -> float:
        return statistics.median(self.samples) if self.samples else 0.0

    @property
    def stdev(self) -> float:
        return statistics.stdev(self.samples) if len(self.samples) > 1 else 0.0

    @property
    def best(self) -> float:
        return min(self.samples) if self.samples else 0.0

    @property
    def worst(self) -> float:
        return max(self.samples) if self.samples else 0.0


@dataclass
class SelfTestBenchmarkReport:
    """Combined report for self-test and benchmark activity."""

    test_results: list[PytestRunResult] = field(default_factory=list)
    benchmark_results: list[BenchmarkResult] = field(default_factory=list)
    summary: str = ""


class SelfTestBenchmarkMode:
    """
    Run RootAct's own tests and lightweight benchmarks.

    This mode is useful after changes to verify that the system still behaves
    correctly and to catch performance regressions on small, deterministic
    workloads. It is intentionally dependency-free beyond the standard library.
    """

    _ROOT_KNOT = _ROOT_KNOT

    def __init__(self) -> None:
        self.test_results: list[PytestRunResult] = []
        self.benchmark_results: list[BenchmarkResult] = []

    def run_tests(
        self,
        test_paths: list[str | Path] | None = None,
        python_executable: str = "python",
    ) -> PytestRunResult:
        """
        Run pytest against the supplied paths and capture the result.

        If ``test_paths`` is empty or None, pytest is invoked with no positional
        arguments and will discover tests in the current directory.
        """
        command = [python_executable, "-m", "pytest", "-q"]
        if test_paths:
            command.extend(str(p) for p in test_paths)

        start = time.perf_counter()
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
        )
        elapsed = time.perf_counter() - start

        passed, failed = self._parse_pytest_summary(proc.stdout + proc.stderr)
        result = PytestRunResult(
            command=command,
            returncode=proc.returncode,
            passed=passed,
            failed=failed,
            output=(
                f"elapsed={elapsed:.3f}s\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            ).strip(),
        )
        self.test_results.append(result)
        return result

    @staticmethod
    def _parse_pytest_summary(output: str) -> tuple[int, int]:
        """Extract passed/failed counts from pytest's short summary."""
        passed = 0
        failed = 0
        for line in output.splitlines():
            stripped = line.strip()
            # Short-summary lines like "5 passed", "2 failed".
            if stripped.startswith("passed"):
                try:
                    passed = int(stripped.split()[1])
                except (IndexError, ValueError):
                    pass
            elif stripped.startswith("failed"):
                try:
                    failed = int(stripped.split()[1])
                except (IndexError, ValueError):
                    pass
            elif " passed" in stripped and " failed" not in stripped:
                # Discovery line like "5 passed in 0.01s".
                try:
                    passed = int(stripped.split()[0])
                except (IndexError, ValueError):
                    pass
            elif " failed" in stripped and " passed" not in stripped:
                # Discovery line like "2 failed in 0.01s".
                try:
                    failed = int(stripped.split()[0])
                except (IndexError, ValueError):
                    pass
        return passed, failed

    def run_benchmark(
        self,
        name: str,
        func: Callable[[], Any],
        iterations: int = 10,
        warmup: int = 1,
    ) -> BenchmarkResult:
        """
        Run ``func`` repeatedly and record timing statistics.

        The warmup iterations are discarded so that cold-start effects do not
        skew the reported numbers.
        """
        for _ in range(max(0, warmup)):
            func()

        samples: list[float] = []
        for _ in range(max(1, iterations)):
            start = time.perf_counter()
            func()
            end = time.perf_counter()
            samples.append(end - start)

        result = BenchmarkResult(name=name, samples=samples)
        self.benchmark_results.append(result)
        return result

    def report(self) -> SelfTestBenchmarkReport:
        """Return a structured report of all tests and benchmarks run so far."""
        total_passed = sum(r.passed for r in self.test_results)
        total_failed = sum(r.failed for r in self.test_results)
        total_tests = total_passed + total_failed
        parts: list[str] = []
        parts.append(
            f"Tests: {total_passed}/{total_tests} passed, {total_failed} failed."
        )
        if self.benchmark_results:
            parts.append("Benchmarks:")
            for bm in self.benchmark_results:
                parts.append(
                    f"  {bm.name}: mean={bm.mean:.6f}s, "
                    f"median={bm.median:.6f}s, best={bm.best:.6f}s, "
                    f"worst={bm.worst:.6f}s (n={len(bm.samples)})"
                )
        else:
            parts.append("No benchmarks recorded.")

        return SelfTestBenchmarkReport(
            test_results=list(self.test_results),
            benchmark_results=list(self.benchmark_results),
            summary="\n".join(parts),
        )
