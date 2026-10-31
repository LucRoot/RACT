"""One way to start git, with the full hardening (B-206).

LR:: Only ``tools/git_tools`` applied the whole of G-239's hardening (fsmonitor
off, no pager, no external diff or signing program, an empty hooks folder,
the GIT_* redirects and RACT's own variables stripped from the environment).
About 35 other places started git with part of it or none: a repository's
``core.fsmonitor`` or hooks could then run a program for RACT's own reads.
``run_git`` is that hardening for every caller. ``extra_env`` is for the
variables RACT itself sets after the filtering (a temporary index for a
snapshot, an identity for a step commit); nothing the operator's shell sets
passes through it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ract import programs


def git_command(*args: str, hooks: bool = False) -> list[str]:
    """The argv ``run_git`` starts: git's full path, the hardening, then *args*."""
    from ract.tools.git_tools import git_argv

    return [programs.git(), *git_argv(*args, hooks=hooks)[1:]]


def run_git(
    *args: str,
    cwd: Path | str | None = None,
    extra_env: dict[str, str] | None = None,
    hooks: bool = False,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """Run git with the hardening; *kwargs* go to ``subprocess.run``.

    Output is captured and a failing exit is returned, not raised, unless the
    caller asks otherwise.
    """
    from ract.tools.git_tools import git_env

    env = git_env()
    if extra_env:
        env.update(extra_env)
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("check", False)
    return subprocess.run(git_command(*args, hooks=hooks), cwd=cwd, env=env, **kwargs)


__all__ = ["git_command", "run_git"]
