from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

from rootact.coverage_reporter import CoverageReporter, _ROOT_KNOT


def _make_example_project(tmp_path: Path) -> tuple[str, str]:
    """Create a minimal source + tests layout and return both directory paths."""
    source_dir = tmp_path / "example_src"
    tests_dir = tmp_path / "example_tests"
    source_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "dummy.py").write_text("print('hello')\n")
    (tests_dir / "test_dummy.py").write_text("def test_dummy(): pass\n")
    return str(source_dir), str(tests_dir)


def test_report_returns_non_empty_string(tmp_path: Path) -> None:
    """The report method must return a non-empty string."""
    reporter = CoverageReporter()
    source_dir, tests_dir = _make_example_project(tmp_path)
    result = reporter.report(source_dir, tests_dir)
    assert isinstance(result, str)
    assert len(result) > 0


def test_report_includes_tested_and_untested_modules(tmp_path: Path) -> None:
    """The report must list tested and untested modules."""
    reporter = CoverageReporter()
    source_dir, tests_dir = _make_example_project(tmp_path)
    result = reporter.report(source_dir, tests_dir)
    assert "Tested Modules" in result
    assert "Untested Modules" in result


def test_report_includes_coverage_percentage(tmp_path: Path) -> None:
    """The report must include a coverage percentage."""
    reporter = CoverageReporter()
    source_dir, tests_dir = _make_example_project(tmp_path)
    result = reporter.report(source_dir, tests_dir)
    assert "Coverage:" in result
    assert "%" in result


def test_report_is_deterministic(tmp_path: Path) -> None:
    """The report must be deterministic for the same inputs."""
    reporter = CoverageReporter()
    source_dir, tests_dir = _make_example_project(tmp_path)
    result1 = reporter.report(source_dir, tests_dir)
    result2 = reporter.report(source_dir, tests_dir)
    assert result1 == result2


def test_root_knot_is_used() -> None:
    """The source module must define _ROOT_KNOT exactly once at module scope."""
    import rootact.coverage_reporter as coverage_module

    assert hasattr(coverage_module, "_ROOT_KNOT")
    from rootact.coverage_reporter import _ROOT_KNOT as source_knot

    assert _ROOT_KNOT is source_knot


# RACT 0.1.0 - Initial Public Release
