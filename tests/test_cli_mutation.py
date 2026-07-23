# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the `ract mutation` CLI command."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from ract.cli import main
from ract.mutation_runner import MutationReport


def test_mutation_run_command_prints_report(tmp_path, monkeypatch, capsys):
    script = tmp_path / "mutmut.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")

    def _fake_run(_project_dir, *, script_path=None, timeout=None, wsl_distro=None):
        from ract.rooted import Rooted

        return Rooted(
            value=MutationReport(killed=90, survived=10, timeout=0, error=0),
            assumption="ok",
            confidence=1.0,
        )

    monkeypatch.setattr("ract.cli.run_mutation_tests", _fake_run)
    config = tmp_path / "ract.yaml"
    config.write_text("", encoding="utf-8")

    rc = main(["mutation", "run", "--script", str(script), "--config", str(config)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "90.0%" in captured.out


def test_mutation_run_command_passes_wsl_distro(tmp_path, monkeypatch, capsys):
    script = tmp_path / "mutmut.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    captured_distro = []

    def _fake_run(_project_dir, *, script_path=None, timeout=None, wsl_distro=None):
        from ract.rooted import Rooted

        captured_distro.append(wsl_distro)
        return Rooted(
            value=MutationReport(killed=90, survived=10, timeout=0, error=0),
            assumption="ok",
            confidence=1.0,
        )

    monkeypatch.setattr("ract.cli.run_mutation_tests", _fake_run)
    config = tmp_path / "ract.yaml"
    config.write_text("", encoding="utf-8")

    rc = main(
        [
            "mutation",
            "run",
            "--script",
            str(script),
            "--wsl-distro",
            "Ubuntu-24.04",
            "--config",
            str(config),
        ]
    )
    assert rc == 0
    assert captured_distro == ["Ubuntu-24.04"]


def test_mutation_run_command_reports_failure(tmp_path, monkeypatch, capsys):
    script = tmp_path / "mutmut.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")

    def _fake_run(_project_dir, *, script_path=None, timeout=None, wsl_distro=None):
        from ract.rooted import Rooted

        return Rooted(
            value=None,
            assumption="script exists",
            confidence=0.0,
            error="mutation runner not found",
        )

    monkeypatch.setattr("ract.cli.run_mutation_tests", _fake_run)
    config = tmp_path / "ract.yaml"
    config.write_text("", encoding="utf-8")

    rc = main(["mutation", "run", "--script", str(script), "--config", str(config)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "mutation testing failed" in captured.err


# RACT 0.1.1 - Trust and tooling
