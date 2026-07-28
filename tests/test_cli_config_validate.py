"""Tests for the ract config validate CLI verb."""

from __future__ import annotations


import subprocess
import sys


def test_cli_config_validate_passes_with_valid_config(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n  name: RACT\nproviders:\n  local:\n    adapter: local_http\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "config",
            "validate",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "valid" in result.stdout


def test_cli_config_validate_fails_with_missing_project_name(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n  name: ''\nproviders:\n  local:\n    adapter: local_http\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "config",
            "validate",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout
    assert "project.name" in result.stderr


# RACT 0.1.1 - Trust and tooling
