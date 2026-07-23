"""Tests for the ract provider health CLI verb."""

from __future__ import annotations


import json
import subprocess
import sys


def test_cli_provider_health_passes_for_reachable_internal_provider(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n  name: RACT\nproviders:\n  echo:\n    adapter: internal\n    command: [python, -c, print(hello)]\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "provider",
            "health",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data.get("echo") is True


def test_cli_provider_health_fails_with_no_providers(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: RACT\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "provider",
            "health",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout


# RACT 0.1.1 - Trust and tooling
