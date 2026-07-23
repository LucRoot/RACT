# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract doctor --json CLI flag."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_doctor_json_returns_valid_checks():
    result = subprocess.run(
        [sys.executable, "-m", "ract.cli", "doctor", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "passed" in data
    assert "checks" in data
    assert any(check.get("check") == "config_exists" for check in data["checks"])


# RACT 0.1.1 - Trust and tooling
