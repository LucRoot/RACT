"""B-115 / B-024 (slice f, ADR-0048 D8): git as tools, in temporary repositories.

Nothing reaches a remote: the push tests stop before running or use the
scripted runner; a local bare repository stands in for the remote.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ract.tools import run_tool
from ract.tools.git_tools import command_for, git_argv, git_env


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test Author")
    _git(root, "config", "user.email", "author@example.invalid")
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "first")
    return root


def _yes(name, args):
    return True


def test_status_is_structured(repo: Path) -> None:
    (repo / "b.txt").write_text("new\n", encoding="utf-8")
    rooted = run_tool(repo, "git_status", {})
    assert rooted.is_ok(), rooted.error
    entries = rooted.unwrap().facts["entries"]
    assert {"status": "??", "path": "b.txt"} in entries


def test_diff_and_log_read(repo: Path) -> None:
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    diff = run_tool(repo, "git_diff", {}).unwrap()
    assert "-one" in diff.text and "+two" in diff.text
    log = run_tool(repo, "git_log", {"max_count": 5}).unwrap()
    assert log.facts["commits"][0]["subject"] == "first"


def test_a_diff_never_runs_a_repository_textconv_or_external_diff(repo: Path) -> None:
    marker = repo / "ran.txt"
    _git(repo, "config", "diff.evil.textconv", f"sh -c 'touch {marker.as_posix()}'")
    _git(repo, "config", "diff.external", f"sh -c 'touch {marker.as_posix()}'")
    (repo / ".gitattributes").write_text("*.txt diff=evil\n", encoding="utf-8")
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    assert run_tool(repo, "git_diff", {}).is_ok()
    assert not marker.exists()


@pytest.mark.parametrize(
    "tool", ["git_add", "git_commit", "git_branch", "git_worktree"]
)
def test_tier_two_tools_ask_and_a_no_does_nothing(repo: Path, tool: str) -> None:
    args = {
        "git_add": {"paths": ["a.txt"]},
        "git_commit": {"message": "x"},
        "git_branch": {"name": "feature"},
        "git_worktree": {"action": "add", "name": "w1"},
    }[tool]
    if tool == "git_commit":
        # G-239 D8: a commit with nothing staged is refused before it asks.
        (repo / "a.txt").write_text("two\n", encoding="utf-8")
        _git(repo, "add", "a.txt")
    asked: list[str] = []
    rooted = run_tool(
        repo, tool, args, approve_tier_2=lambda n, a: asked.append(n) and False
    )
    assert not rooted.is_ok() and asked == [tool]
    assert "feature" not in _git(repo, "branch")


def test_add_then_commit_uses_the_operators_author(repo: Path) -> None:
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    assert run_tool(repo, "git_add", {"paths": ["a.txt"]}, approve_tier_2=_yes).is_ok()
    rooted = run_tool(repo, "git_commit", {"message": "change a"}, approve_tier_2=_yes)
    assert rooted.is_ok(), rooted.error
    assert rooted.unwrap().facts["hooks"] is False
    assert _git(repo, "log", "-1", "--format=%an|%s").strip() == "Test Author|change a"


def test_a_staged_secret_blocks_the_commit_and_names_the_file(repo: Path) -> None:
    key = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"
    (repo / "config.py").write_text(f"KEY = '{key}'\n", encoding="utf-8")
    run_tool(repo, "git_add", {"paths": ["config.py"]}, approve_tier_2=_yes)
    rooted = run_tool(
        repo, "git_commit", {"message": "add config"}, approve_tier_2=_yes
    )
    assert not rooted.is_ok() and "config.py:1" in rooted.error
    assert key not in rooted.error
    assert _git(repo, "log", "-1", "--format=%s").strip() == "first"


def test_a_repository_hook_never_runs_without_a_grant_rule(repo: Path) -> None:
    marker = repo / "hook-ran.txt"
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch '{marker.as_posix()}'\n", encoding="utf-8")
    hook.chmod(0o755)
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    run_tool(repo, "git_add", {"paths": ["a.txt"]}, approve_tier_2=_yes)
    assert run_tool(repo, "git_commit", {"message": "x"}, approve_tier_2=_yes).is_ok()
    assert not marker.exists()


def test_branch_names_and_paths_that_could_be_options_are_refused(repo: Path) -> None:
    for tool, args in (
        ("git_branch", {"name": "-D"}),
        ("git_branch", {"name": "a..b"}),
        ("git_add", {"paths": ["--all"]}),
        ("git_add", {"paths": ["../outside"]}),
        ("git_diff", {"paths": ["/etc/passwd"]}),
    ):
        assert not run_tool(repo, tool, args, approve_tier_2=_yes).is_ok(), (tool, args)


def test_the_hardening_and_the_environment(repo: Path) -> None:
    argv = git_argv("status")
    assert "core.fsmonitor=false" in argv and any(
        a.startswith("core.hooksPath=") for a in argv
    )
    env = git_env(
        {"GIT_DIR": "/x", "GIT_CONFIG_GLOBAL": "/y", "RACT_RUN_ID": "r", "PATH": "p"}
    )
    assert set(env) == {"PATH", "GIT_TERMINAL_PROMPT"}


def test_the_command_shown_is_the_command_run(repo: Path) -> None:
    from ract.tools.git_tools import AddArgs, CommitArgs

    assert command_for("git_add", AddArgs(paths=["a.txt"])) == [
        "git",
        "add",
        "--",
        "a.txt",
    ]
    assert command_for("git_commit", CommitArgs(message="m")) == [
        "git",
        "commit",
        "-m",
        "m",
    ]


def test_push_without_a_tier3_context_is_refused(repo: Path) -> None:
    rooted = run_tool(repo, "git_push", {"remote": "origin", "branch": "main"})
    assert not rooted.is_ok() and "tier 3" in rooted.error
