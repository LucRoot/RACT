# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract manifest CLI verb."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import subprocess
import sys


def test_cli_manifest_appears_in_help():
    result = subprocess.run(
        [sys.executable, "-m", "rootact.cli", "manifest", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "manifest" in result.stdout
