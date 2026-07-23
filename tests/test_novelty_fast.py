# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for ract novelty scan --fast."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_novelty_scan_fast_returns_json(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
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
