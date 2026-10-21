"""Tests for the cross-platform install script."""

from __future__ import annotations


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


_SCRIPT = Path(__file__).parent.parent / "scripts" / "install.sh"
_unix_only = pytest.mark.skipif(sys.platform == "win32", reason="requires a Unix shell")


def _make_stub_python(stub_dir: Path, log: Path) -> None:
    """Install fake python executables that record argv and fake `-m venv`."""
    stub = stub_dir / "python3"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$@" >> "$STUB_LOG"\n'
        'if [[ "$1" == "--version" ]]; then echo "Python 3.12.0"; exit 0; fi\n'
        'if [[ "$1" == "-m" && "$2" == "venv" ]]; then\n'
        '  mkdir -p "$3/bin"\n'
        "  printf '#!/usr/bin/env bash\\n' > \"$3/bin/activate\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    for alias in ("python3.12", "python3.11", "python"):
        (stub_dir / alias).symlink_to(stub)


def _run_install(tmp_path: Path, *args: str) -> tuple[subprocess.CompletedProcess, str]:
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    log = tmp_path / "calls.log"
    _make_stub_python(stub_dir, log)
    workdir = tmp_path / "not-named-ract"  # the old basename gate would reject this
    workdir.mkdir()
    env = {
        "PATH": f"{stub_dir}:/usr/bin:/bin",
        "STUB_LOG": str(log),
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        ["bash", str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=workdir,
        env=env,
    )
    return result, log.read_text(encoding="utf-8") if log.exists() else ""


@_unix_only
def test_install_sh_is_executable():
    import os

    assert os.access(_SCRIPT, os.X_OK), (
        "scripts/install.sh must be committed executable "
        "(git update-index --chmod=+x scripts/install.sh)"
    )


@_unix_only
def test_venv_flag_without_directory_defaults_to_dot_venv(tmp_path):
    """Regression: `--local --venv` used to exit silently (shift 2 under set -e)."""
    result, calls = _run_install(tmp_path, "--local", "--venv")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "-m venv .venv" in calls
    assert "-m pip install" in calls
    assert "source .venv/bin/activate" in result.stdout


@_unix_only
def test_venv_flag_with_directory_uses_it(tmp_path):
    result, calls = _run_install(tmp_path, "--local", "--venv", "env-x")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "-m venv env-x" in calls


@_unix_only
def test_venv_flag_does_not_swallow_following_option(tmp_path):
    result, _ = _run_install(tmp_path, "--venv", "--help")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Usage: install.sh" in result.stdout


@_unix_only
def test_clone_directory_name_is_not_required(tmp_path):
    result, _ = _run_install(tmp_path, "--local")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "expected 'RACT'" not in result.stderr


# RACT 0.1.1 - Trust and tooling
