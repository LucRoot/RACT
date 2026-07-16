# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _script(name: str) -> Path:
    return Path(sys.executable).with_name(f"{name}.exe")


@pytest.mark.parametrize("name", ["rootact", "ract"])
def test_version(name: str) -> None:
    exe = _script(name)
    if not exe.exists():
        pytest.skip(f"{exe} not installed")
    result = subprocess.run(
        [str(exe), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "0.1.2" in result.stdout, result.stdout


def test_version_via_module() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "rootact.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "0.1.2" in result.stdout, result.stdout
