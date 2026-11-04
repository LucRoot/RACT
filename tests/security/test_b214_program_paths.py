"""B-214: no program RACT starts is taken from the current folder.

``subprocess.run(["git", ...])`` on Windows lets CreateProcess look in the
current folder before PATH unless ``NoDefaultCurrentDirectoryInExePath`` is
set, so a ``git.exe`` a repository ships at its top ran in place of git (reader
repro; this machine sets the variable, which hid it). git is now started by
its full path from ``programs.git()``, and the CLI sets the variable for the
programs it starts by name.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ract import programs
from ract.policy.matcher import resolve_executable


@pytest.fixture
def planted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working folder holding a planted git.exe and git.bat, with the guard variable unset."""
    folder = tmp_path / "repo"
    folder.mkdir()
    for name in ("git.exe", "git.bat", "git", "git.cmd"):
        (folder / name).write_bytes(b"@echo planted> planted.txt\n")
    monkeypatch.chdir(folder)
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([".", "", os.environ.get("PATH", "")]))
    return folder


def test_git_is_never_the_one_in_the_current_folder(planted: Path) -> None:
    found = programs.git()
    assert os.path.isabs(found) or found == "git"
    assert Path(found).parent.resolve() != planted.resolve()


def test_the_call_sites_start_git_by_its_full_path(
    planted: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ract.executor import worktree

    started: list[list[str]] = []
    real_run = subprocess.run

    def spy(argv, *args, **kwargs):  # type: ignore[no-untyped-def]
        started.append(list(argv))
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(worktree.subprocess, "run", spy)
    try:
        worktree.ensure_git_repo(planted)
    except worktree.WorktreeError as exc:
        print(f"not a repository here, as expected: {exc}")
    assert started and started[0][0] == programs.git()
    assert not (planted / "planted.txt").exists()


def test_a_name_with_a_dot_still_gets_its_extension(tmp_path: Path) -> None:
    folder = tmp_path / "bin"
    folder.mkdir()
    exe = folder / ("tool3.11.exe" if os.name == "nt" else "tool3.11")
    exe.write_bytes(b"")
    exe.chmod(0o755)
    found = resolve_executable("tool3.11", str(folder), [])
    assert found is not None and found.casefold() == str(exe.absolute()).casefold()


@pytest.mark.skipif(
    os.name != "nt", reason="the variable is read by Windows CreateProcess"
)
def test_the_cli_sets_the_guard_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    from ract.cli import main

    main(["--version"])
    assert os.environ.get("NoDefaultCurrentDirectoryInExePath") == "1"
