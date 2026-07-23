# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract --init-provider preset validation."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import subprocess
import sys


def test_cli_init_provider_valid_creates_config(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "--init-provider",
            "local",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "rootact.yaml").is_file()
    assert "wrote rootact.yaml" in result.stdout


def test_cli_init_provider_invalid_prints_error(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "--init-provider",
            "invalid-preset",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
    )
    assert result.returncode == 1
    assert "unknown provider preset" in result.stderr.lower()
    assert "Traceback" not in result.stderr


# RACT 0.1.2 - Trust and tooling
