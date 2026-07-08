# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the lint/format repair driver."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import sys

from rootact.lint_format_repair import LintFormatRepair


def test_check_passes_on_clean_project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "clean.py").write_text(
        "def hello():\n    pass\n", encoding="utf-8"
    )
    driver = LintFormatRepair(tmp_path, python_executable=sys.executable, paths=["src"])
    report = driver.check()
    assert report.passed
    assert report.issues == []


def test_check_finds_unused_import(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "dirty.py").write_text(
        "import os\n\ndef hello():\n    pass\n", encoding="utf-8"
    )
    driver = LintFormatRepair(tmp_path, python_executable=sys.executable, paths=["src"])
    report = driver.check()
    assert not report.passed
    assert any(
        "imported but unused" in issue.message.lower() for issue in report.issues
    )


def test_check_finds_format_violation(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ugly.py").write_text(
        "def hello():\n    x=1\n", encoding="utf-8"
    )
    driver = LintFormatRepair(tmp_path, python_executable=sys.executable, paths=["src"])
    report = driver.check()
    assert not report.passed
    assert any(issue.tool == "ruff-format" for issue in report.issues)


def test_build_repair_prompt_returns_none_when_passed(tmp_path):
    driver = LintFormatRepair(tmp_path, python_executable=sys.executable, paths=["src"])
    report = driver.check()
    rooted = driver.build_repair_prompt(report)
    assert not rooted.is_ok()


def test_build_repair_prompt_contains_issues(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "dirty.py").write_text(
        "import os\n\ndef hello():\n    pass\n", encoding="utf-8"
    )
    driver = LintFormatRepair(tmp_path, python_executable=sys.executable, paths=["src"])
    report = driver.check()
    rooted = driver.build_repair_prompt(report)
    assert rooted.is_ok()
    prompt = rooted.unwrap()["prompt"]
    assert "Fix the following" in prompt
    assert "dirty.py" in prompt


def test_parse_ruff_line():
    driver = LintFormatRepair(".")
    issue = driver._parse_line(
        "ruff-check", "src/module.py:5:1: F401 `os` imported but unused"
    )
    assert issue is not None
    assert issue.file == "src/module.py"
    assert issue.line == 5


def test_parse_mypy_line():
    driver = LintFormatRepair(".")
    issue = driver._parse_line(
        "mypy", 'src/module.py:10: error: Argument 1 to "foo" has incompatible type'
    )
    assert issue is not None
    assert issue.file == "src/module.py"
    assert issue.line == 10


# RACT 0.1.0 - Initial Public Release
