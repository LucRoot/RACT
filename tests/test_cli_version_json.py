# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract --version --json CLI output."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def _run(args):
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_version_json_emits_json():
    result = _run(["--version", "--json"])
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["name"] == "RACT"
    assert data["version"].startswith("0.")


def test_cli_version_plain_stays_plain():
    result = _run(["--version"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("RACT ")
    assert "0." in result.stdout
