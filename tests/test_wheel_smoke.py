"""Smoke test that the RACT wheel builds and entry points work."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import ract


@pytest.mark.skipif(
    sys.platform != "win32", reason="virtualenv path tests are Windows-focused"
)
def test_wheel_builds_and_entry_points_work(tmp_path: Path):
    """Build a wheel, install it into a fresh venv, and verify entry points."""
    repo_dir = Path(__file__).parent.parent.resolve()
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()

    # Build the wheel.
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "-w",
            str(wheelhouse),
            str(repo_dir),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert build.returncode == 0, build.stderr

    wheels = list(wheelhouse.glob("ract-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, found {wheels}"
    wheel = wheels[0]
    assert ract.__version__ in wheel.name, (
        f"expected version {ract.__version__} in wheel name: {wheel.name}"
    )

    # Create a fresh virtual environment.
    venv_dir = tmp_path / "venv"
    venv_python = venv_dir / "Scripts" / "python.exe"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

    # Install the wheel.
    install = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", str(wheel)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert install.returncode == 0, install.stderr

    # Verify both entry points report the expected version.
    for entry_point in ("ract", "ract"):
        result = subprocess.run(
            [str(venv_dir / "Scripts" / f"{entry_point}.exe"), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert ract.__version__ in result.stdout, (
            f"expected {ract.__version__} from {entry_point}: {result.stdout}"
        )

    # Verify ract doctor passes in the installed environment.
    doctor = subprocess.run(
        [str(venv_dir / "Scripts" / "ract.exe"), "doctor"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        cwd=str(repo_dir),
    )
    assert doctor.returncode == 0, doctor.stderr
    assert "passed" in doctor.stdout.lower(), doctor.stdout
