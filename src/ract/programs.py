"""The programs RACT starts, found by their full path (B-214).

LR:: ``subprocess.run(["git", ...])`` on Windows lets CreateProcess look in the
current folder before PATH unless ``NoDefaultCurrentDirectoryInExePath`` is
set, so a ``git.exe`` or ``git.bat`` a repository ships at its top ran in
place of git (reader repro; this machine sets the variable, which hid it).
``git()`` resolves git once with ``matcher.resolve_executable``, which never
searches the current folder or a relative PATH entry, and every place that
starts git uses it. ``no_current_folder_search()`` sets the variable for this
process and its children, so the other programs RACT starts (python, rg,
bwrap, wsl) are not taken from the current folder either.
"""

from __future__ import annotations

import os
from functools import lru_cache

_VARIABLE = "NoDefaultCurrentDirectoryInExePath"


def git() -> str:
    """The full path of git on PATH, never one in the current folder.

    When git is not on PATH the bare name is returned, and starting it fails
    with the usual "not found" error the callers already handle. The answer is
    kept per PATH value, so a changed PATH is searched again.
    """
    return _git_on(os.environ.get("PATH", ""))


@lru_cache(maxsize=8)
def _git_on(path_env: str) -> str:
    from ract.policy.matcher import resolve_executable

    return resolve_executable("git", path_env, []) or "git"


def no_current_folder_search() -> None:
    """On Windows, stop CreateProcess from searching the current folder first."""
    if os.name == "nt":
        os.environ[_VARIABLE] = "1"


__all__ = ["git", "no_current_folder_search"]
