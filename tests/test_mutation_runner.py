# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the mutation-testing runner and parser."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

from rootact.mutation_runner import (
    MutationReport,
    _parse_mutmut_results,
    run_mutation_tests,
)


def test_parse_results_extracts_counts():
    text = (
        "Mutation testing results:\n\n"
        "Survived 🙁 (5)\n"
        "Timed out ⏰ (2)\n"
        "Killed 😎 (43)\n"
    )
    report = _parse_mutmut_results(text)
    assert report is not None
    assert report.killed == 43
    assert report.survived == 5
    assert report.timeout == 2
    assert report.error == 0
    assert report.total == 50
    assert report.mutation_score == 86.0


def test_parse_results_all_killed_shortcut():
    report = _parse_mutmut_results("All mutations are killed! ✔")
    assert report is not None
    assert report.killed == 1
    assert report.survived == 0
    assert report.mutation_score == 100.0


def test_parse_results_none_when_no_counts():
    assert _parse_mutmut_results("Some unrelated output") is None


def test_run_mutation_tests_missing_script(tmp_path):
    result = run_mutation_tests(tmp_path)
    assert not result.is_ok()
    assert "not found" in (result.error or "").lower()


def test_run_mutation_tests_parses_output(monkeypatch, tmp_path):
    script = tmp_path / "mutmut.sh"
    script.write_text("#!/bin/bash\necho 'Killed 😎 (90)'\n", encoding="utf-8")

    def _fake_run(cmd, **kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(
            returncode=0,
            stdout="Killed 😎 (90)\nSurvived 🙁 (10)\n",
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", _fake_run)
    result = run_mutation_tests(tmp_path, script_path=script)
    assert result.is_ok(), result.error
    report = result.unwrap()
    assert isinstance(report, MutationReport)
    assert report.killed == 90
    assert report.survived == 10
    assert report.mutation_score == 90.0


def test_run_mutation_tests_timeout(monkeypatch, tmp_path):
    script = tmp_path / "mutmut.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")

    def _fake_run(cmd, **kwargs):
        import subprocess

        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1.0))

    monkeypatch.setattr("subprocess.run", _fake_run)
    result = run_mutation_tests(tmp_path, script_path=script)
    assert not result.is_ok()
    assert "timed out" in (result.error or "").lower()


def test_run_mutation_tests_missing_runner(monkeypatch, tmp_path):
    script = tmp_path / "mutmut.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")

    def _fake_run(cmd, **kwargs):
        raise FileNotFoundError("bash")

    monkeypatch.setattr("subprocess.run", _fake_run)
    result = run_mutation_tests(tmp_path, script_path=script)
    assert not result.is_ok()
    assert "not found" in (result.error or "").lower()


def test_run_mutation_tests_unparseable_output(monkeypatch, tmp_path):
    script = tmp_path / "mutmut.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")

    def _fake_run(cmd, **kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(returncode=0, stdout="no counts here", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    result = run_mutation_tests(tmp_path, script_path=script)
    assert not result.is_ok()
    assert "parse" in (result.error or "").lower()


def test_parse_results_extracts_error_count():
    text = "Error (3)\nKilled 😎 (47)\n"
    report = _parse_mutmut_results(text)
    assert report is not None
    assert report.error == 3
    assert report.killed == 47


def test_report_str_with_zero_total():
    report = MutationReport(killed=0, survived=0, timeout=0, error=0)
    assert "0.0%" in str(report)


def test_report_str_with_score():
    report = MutationReport(killed=90, survived=10, timeout=0, error=0)
    assert "90.0%" in str(report)


def test_resolve_runner_command_on_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    from rootact.mutation_runner import _resolve_runner_command

    cmd = _resolve_runner_command(Path("/tmp/script.sh"))
    assert cmd[0] == "wsl"


# RACT 0.1.0 - Initial Public Release
