"""S-024: RACT's own commits carry RACT's identity, never the machine's.

Step commits used a plain `git commit`, so they took user.name and
user.email from the machine (a personal or employer identity on branches the
operator may push), and failed with "Author identity unknown" where none is
set, as on a fresh CI runner.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.ux import run_baseline as rb


def _git(ws: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=ws, capture_output=True, text=True, check=True, env=env
    ).stdout.strip()


def _isolated_env(tmp_path: Path, global_config: str | None) -> dict[str, str]:
    """An environment whose git sees no system config and the given global one."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    config = tmp_path / "gitconfig"
    config.write_text(global_config or "", encoding="utf-8")
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith(("RACT_", "GIT_"))
    }
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home),
            "GIT_CONFIG_GLOBAL": str(config),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    return env


def _run(ws: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", "--config", "ract.yaml", "fix add"],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def _workspace(tmp_path: Path, base_url: str) -> tuple[Path, str]:
    ws = rb._workspace(tmp_path, "ws", git=True, files=rb.CALC_FILES)
    rb._configure(ws, base_url, "fake-coder")
    # The run below uses an isolated git config. Pin line-ending handling in
    # the repository itself, so the repository and the run agree on it.
    autocrlf = subprocess.run(
        ["git", "config", "--get", "core.autocrlf"],
        cwd=ws,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if autocrlf:
        subprocess.run(["git", "config", "core.autocrlf", autocrlf], cwd=ws, check=True)
    ident = ["-c", "user.name=Operator", "-c", "user.email=op@example.invalid"]
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    subprocess.run(["git", *ident, "commit", "-q", "-m", "c"], cwd=ws, check=True)
    return ws, _git(ws, "rev-parse", "HEAD")


def _step_authors(ws: Path) -> list[str]:
    branch = _git(ws, "branch", "--list", "rootact/step/*", "--format=%(refname:short)")
    assert branch, "no step branch"
    # The step commit and its parent, the base snapshot.
    return _git(ws, "log", "-2", "--format=%an <%ae>|%cn <%ce>", branch).splitlines()


def test_a_step_commits_on_a_machine_with_no_git_identity(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws, head = _workspace(tmp_path, server.base_url)

    result = _run(ws, _isolated_env(tmp_path, None))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Author identity unknown" not in result.stdout + result.stderr
    assert "return a + b" in (ws / "src" / "calc.py").read_text(encoding="utf-8")
    assert _step_authors(ws) == ["ract <ract@localhost>|ract <ract@localhost>"] * 2
    assert _git(ws, "rev-parse", "HEAD") == head  # the operator's branch is untouched


def test_the_machine_identity_never_reaches_a_step_commit(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws, head = _workspace(tmp_path, server.base_url)
    sentinel = (
        "[user]\n\tname = Sentinel Person\n\temail = sentinel@example.invalid\n"
        "[commit]\n\tgpgsign = true\n"
    )
    env = _isolated_env(tmp_path, sentinel)
    env["GIT_AUTHOR_NAME"] = "Sentinel From Env"

    result = _run(ws, env)

    assert result.returncode == 0, result.stdout + result.stderr
    authors = _step_authors(ws)
    assert authors == ["ract <ract@localhost>|ract <ract@localhost>"] * 2
    assert "Sentinel" not in "\n".join(authors)
    assert _git(ws, "rev-parse", "HEAD") == head
