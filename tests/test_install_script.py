# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the cross-platform install script."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import subprocess
import sys
from pathlib import Path

import pytest


def test_install_sh_script_exists():
    script = Path(__file__).parent.parent / "scripts" / "install.sh"
    assert script.is_file()
    assert "RACT" in script.read_text(encoding="utf-8")


@pytest.mark.skipif(
    sys.platform == "win32", reason="bash syntax check requires Unix shell"
)
def test_install_sh_syntax_is_valid():
    script = Path(__file__).parent.parent / "scripts" / "install.sh"
    result = subprocess.run(
        ["bash", "-n", str(script)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
