# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract init --list-templates CLI flag."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import subprocess
import sys


def test_cli_init_list_templates_prints_templates():
    result = subprocess.run(
        [sys.executable, "-m", "ract.cli", "init", "--list-templates"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


# RACT 0.1.1 - Trust and tooling
