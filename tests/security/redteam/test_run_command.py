"""B-027 red team: the command core (``run_command``, the matcher's resolution).

The flood and the held pipe run a real Python child in a temporary project,
as G-215 allows for these two; every other case uses the scripted runner.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from ract.policy.matcher import Match, classify, resolve_executable
from ract.security.sandbox_env import NEVER_PASSTHROUGH
from ract.tools.command import (
    OUTPUT_FLOOD_BYTES,
    PIPES_HELD_NOTE,
    ProcessRunner,
    RawRun,
    ScriptedRunner,
    run_command,
)


class Rule:
    id = "redteam"
    cwd = "step_worktree"
    timeout_s = 60
    max_output_bytes = 4096
    home = "isolated"
    env_extra: list[str] = []


def _python(code: str) -> Match:
    return Match(
        "matches", "the rule", ("python", "-c", code), sys.executable, "redteam"
    )


def _run(tmp_path: Path, match: Match, runner, **kw):
    return run_command(
        match,
        worktree=tmp_path,
        rule=Rule(),
        runner=runner,
        process_env=kw.pop("env", dict(os.environ)),
        project=tmp_path,
        **kw,
    )


def test_endless_output_is_killed_at_the_ceiling(tmp_path: Path) -> None:
    code = "import sys\nb = b'x' * 65536\nwhile True:\n    sys.stdout.buffer.write(b)\n"
    started = time.monotonic()
    result = _run(tmp_path, _python(code), ProcessRunner()).unwrap()
    assert (
        result.killed_by == "output_flood" and result.stdout_bytes > OUTPUT_FLOOD_BYTES
    )
    assert time.monotonic() - started < 50 and len(result.stdout) < 10_000


def test_a_grandchild_holding_the_pipes_does_not_hold_ract(tmp_path: Path) -> None:
    code = (
        "import subprocess, sys\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(40)'],"
        " stdout=sys.stdout, stderr=subprocess.DEVNULL)\n"
        "sys.stderr.write(str(p.pid))\nsys.stderr.flush()\n"
    )
    started = time.monotonic()
    result = _run(tmp_path, _python(code), ProcessRunner()).unwrap()
    try:
        assert PIPES_HELD_NOTE in result.notes and time.monotonic() - started < 30
    finally:
        pid = int(result.stderr.strip() or 0)
        if pid:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)


def _tool(tmp_path: Path, body: bytes = b"first") -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    exe = bin_dir / ("tool.exe" if os.name == "nt" else "tool")
    exe.write_bytes(body)
    exe.chmod(0o755)
    return exe


def test_an_executable_swapped_between_classify_and_run_is_refused(
    tmp_path: Path,
) -> None:
    exe = _tool(tmp_path)
    project = tmp_path / "p"
    project.mkdir()
    match = classify(["tool"], None, project, path_env=str(exe.parent))
    exe.write_bytes(b"swapped")
    runner = ScriptedRunner([{}])
    rooted = _run(project, match, runner)
    assert not rooted.is_ok() and "changed after it was resolved" in rooted.error
    assert runner.calls == []


class Rewrites:
    name = "fake"

    def __init__(self, exe: Path) -> None:
        self.exe = exe

    def run(self, argv, *, cwd, env, timeout_s):
        self.exe.write_bytes(b"rewritten by the command")
        return RawRun(0, b"", b"", 1)


def test_a_command_that_rewrites_itself_is_recorded_as_it_was(tmp_path: Path) -> None:
    exe = _tool(tmp_path)
    project = tmp_path / "p"
    project.mkdir()
    match = classify(["tool"], None, project, path_env=str(exe.parent))
    result = _run(project, match, Rewrites(exe)).unwrap()
    assert result.executable_sha256 == hashlib.sha256(b"first").hexdigest()


def test_ract_names_and_secrets_never_reach_the_command(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin", "RACT_RUN_ID": "r1"}
    env.update({name: "leak" for name in NEVER_PASSTHROUGH})
    env.update(
        {
            "RACT_TIER_3_ENABLED": "1",
            "RACT_FAKE_RUNNER": "x",
            "RACT_OPERATOR_KEY": "k",
            "RACT_KEY_HOSTS": "h",
        }
    )
    runner = ScriptedRunner([{}])
    _run(tmp_path, _python("1"), runner, env=env)
    seen = runner.calls[0]["env"]
    assert "leak" not in seen.values()
    assert not [k for k in seen if k.upper().startswith("RACT_") and k != "RACT_RUN_ID"]
    assert seen.get("RACT_RUN_ID") == "r1"
    assert all(
        seen[k] == seen["HOME"] for k in ("HOME", "XDG_CONFIG_HOME") if k in seen
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows searches the current folder first")
def test_a_shim_planted_in_the_working_folder_is_never_chosen(
    tmp_path: Path, monkeypatch
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    for name in ("git.cmd", "git.exe", "python.bat"):
        (worktree / name).write_text("", encoding="utf-8")
    monkeypatch.chdir(worktree)
    system = os.environ.get("SystemRoot", r"C:\Windows")
    assert resolve_executable("git", system, [worktree]) is None
    assert resolve_executable("python", system, [worktree]) is None


def _folder_link(target: Path, link: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_a_path_through_a_planted_junction_leaves_the_project_and_is_refused(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.py").write_text("", encoding="utf-8")
    project = tmp_path / "p"
    project.mkdir()
    _folder_link(outside, project / "tools")
    match = classify(["tools/evil.py"], None, project, path_env="")
    assert match.outcome == "refused" and "outside the project" in match.reason


def test_an_executable_inside_the_project_on_path_is_skipped(tmp_path: Path) -> None:
    project = tmp_path / "p"
    (project / "bin").mkdir(parents=True)
    name = "tool.exe" if os.name == "nt" else "tool"
    (project / "bin" / name).write_text("", encoding="utf-8")
    os.chmod(project / "bin" / name, 0o755)
    assert resolve_executable("tool", str(project / "bin"), [project]) is None
