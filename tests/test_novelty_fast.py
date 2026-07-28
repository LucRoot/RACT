"""Tests for ract novelty scan --fast."""

from __future__ import annotations


import json
import subprocess
import sys


def test_cli_novelty_scan_fast_returns_json(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "novelty",
            "scan",
            "--fast",
            "--json",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "scores" in data


# RACT 0.1.1 - Trust and tooling
