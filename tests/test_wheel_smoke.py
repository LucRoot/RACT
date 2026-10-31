"""Smoke test that the RACT wheel builds and entry points work."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import sysconfig
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

    # Build the wheel. With the build backend already installed, pip builds it
    # in place of a new isolated environment it would fill from the package
    # index (most of this test's time, B-152).
    isolation = (
        []
        if importlib.util.find_spec("hatchling") is None
        else ["--no-build-isolation"]
    )
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            *isolation,
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

    # Create a fresh virtual environment. This interpreter's pip installs into
    # it, and RACT's dependencies are read from this interpreter's packages
    # through a .pth line, so the test installs only the wheel and never
    # reaches the package index (B-152).
    venv_dir = tmp_path / "venv"
    venv_python = venv_dir / "Scripts" / "python.exe"
    # The new environment runs without this run's PYTHONPATH, which points at
    # the checkout's src and would be imported in place of the installed wheel.
    clean_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv_dir)], check=True
    )
    (venv_dir / "Lib" / "site-packages" / "ract_test_dependencies.pth").write_text(
        sysconfig.get_paths()["purelib"] + "\n", encoding="utf-8"
    )

    # Install the wheel.
    install = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "--python",
            str(venv_python),
            "install",
            "--quiet",
            "--no-deps",
            "--no-index",
            str(wheel),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert install.returncode == 0, install.stderr

    # The installed wheel is what the new environment imports, not this checkout.
    where = subprocess.run(
        [str(venv_python), "-c", "import ract; print(ract.__file__)"],
        env=clean_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert where.returncode == 0, where.stderr
    assert Path(where.stdout.strip()).resolve().is_relative_to(venv_dir.resolve()), (
        where.stdout
    )

    # Verify both entry points report the expected version.
    for entry_point in ("ract", "ract"):
        result = subprocess.run(
            [str(venv_dir / "Scripts" / f"{entry_point}.exe"), "--version"],
            env=clean_env,
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
        env=clean_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        cwd=str(repo_dir),
    )
    assert doctor.returncode == 0, doctor.stderr
    assert "passed" in doctor.stdout.lower(), doctor.stdout
