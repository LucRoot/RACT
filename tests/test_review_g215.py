"""G-215 (the MANAGER's senior review, part 3): ``tools/command.py``, C1 to C5.

C1 and C2 run the real runner with a Python child, as the review allows: a
temporary project, an approved rule and the command handed to run_command
directly (the matcher would refuse ``python -c``; nothing here goes through
it). Every child is bounded and any process a test starts is killed by it.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from ract.policy.matcher import Match, classify
from ract.tools.command import (
    OUTPUT_FLOOD_BYTES,
    PIPES_HELD_NOTE,
    ProcessRunner,
    RawRun,
    ScriptedRunner,
    run_command,
)


class Rule:
    id = "tests"
    cwd = "step_worktree"
    timeout_s = 60
    max_output_bytes = 4096
    home = "isolated"
    env_extra: list[str] = []


def _python(code: str) -> Match:
    return Match(
        "matches", "the rule tests", ("python", "-c", code), sys.executable, "tests"
    )


def _run(tmp_path: Path, match: Match, runner, rule=None):
    return run_command(
        match,
        worktree=tmp_path,
        rule=rule or Rule(),
        runner=runner,
        process_env=dict(os.environ),
        project=tmp_path,
    )


def test_c1_an_endless_stream_is_killed_at_the_ceiling(tmp_path: Path) -> None:
    code = "import sys\nb = b'x' * 65536\nwhile True:\n    sys.stdout.buffer.write(b)\n"
    started = time.monotonic()
    result = _run(tmp_path, _python(code), ProcessRunner()).unwrap()
    assert result.killed_by == "output_flood" and not result.passed
    assert result.stdout_bytes > OUTPUT_FLOOD_BYTES and result.stdout_truncated
    assert len(result.stdout) < 10_000  # the cap, not the stream
    assert any("64 MiB" in n for n in result.notes)
    assert time.monotonic() - started < 50  # long before the 60 s timeout


def test_c1_the_hash_and_the_count_cover_every_byte(tmp_path: Path) -> None:
    size = 3 * 1_048_576
    code = (
        "import sys\n"
        f"data = bytes(i % 251 for i in range({size}))\n"
        "sys.stdout.buffer.write(data)\n"
    )
    result = _run(tmp_path, _python(code), ProcessRunner()).unwrap()
    expected = bytes(i % 251 for i in range(size))
    assert result.exit_code == 0 and result.killed_by is None
    assert result.stdout_bytes == size
    assert result.stdout_sha256 == hashlib.sha256(expected).hexdigest()
    assert result.stdout_truncated and "bytes dropped" in result.stdout


def test_c2_a_grandchild_holding_the_pipe_does_not_hold_ract(tmp_path: Path) -> None:
    code = (
        "import subprocess, sys\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(40)'],"
        " stdout=sys.stdout, stderr=subprocess.DEVNULL)\n"
        "sys.stderr.write(str(p.pid))\n"
        "sys.stderr.flush()\n"
    )
    started = time.monotonic()
    result = _run(tmp_path, _python(code), ProcessRunner()).unwrap()
    elapsed = time.monotonic() - started
    try:
        assert PIPES_HELD_NOTE in result.notes, result.notes
        assert elapsed < 30, elapsed
    finally:
        pid = int(result.stderr.strip() or 0)
        if pid:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)


def _tool(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / ("tool.exe" if os.name == "nt" else "tool")
    exe.write_bytes(b"first")
    exe.chmod(0o755)
    return exe


def test_c3_the_matcher_says_the_digest_it_saw(tmp_path: Path) -> None:
    exe = _tool(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    match = classify(["tool"], None, project, path_env=str(exe.parent))
    assert match.outcome == "asks", match
    assert match.executable_sha256 == hashlib.sha256(b"first").hexdigest()


def test_c3_an_executable_changed_after_classification_is_refused(
    tmp_path: Path,
) -> None:
    exe = _tool(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    match = classify(["tool"], None, project, path_env=str(exe.parent))
    exe.write_bytes(b"second")
    runner = ScriptedRunner([{}])
    rooted = _run(project, match, runner)
    assert not rooted.is_ok()
    assert "changed after it was resolved" in rooted.error and runner.calls == []


class Rewrites:
    """A runner whose command rewrites its own executable while it runs."""

    name = "fake"

    def __init__(self, exe: Path) -> None:
        self.exe = exe

    def run(self, argv, *, cwd, env, timeout_s):
        self.exe.write_bytes(b"rewritten")
        return RawRun(0, b"", b"", 1)


def test_c3_the_record_keeps_the_hash_from_before_the_spawn(tmp_path: Path) -> None:
    exe = _tool(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    match = classify(["tool"], None, project, path_env=str(exe.parent))
    result = _run(project, match, Rewrites(exe)).unwrap()
    assert result.executable_sha256 == hashlib.sha256(b"first").hexdigest()


def test_c4_the_step_home_is_removed_and_the_record_says_so(tmp_path: Path) -> None:
    runner = ScriptedRunner([{}])
    result = _run(tmp_path, _python("1"), runner).unwrap()
    home = Path(runner.calls[0]["env"]["HOME"])
    assert home.name.startswith("ract-step-home-") and not home.exists()
    assert result.step_home == "removed"


def test_c4_a_real_home_makes_no_folder(tmp_path: Path, monkeypatch) -> None:
    class Real(Rule):
        home = "real"

    made: list[str] = []
    monkeypatch.setattr(
        "ract.tools.command.tempfile.mkdtemp", lambda **kw: made.append("x") or ""
    )
    result = _run(tmp_path, _python("1"), ScriptedRunner([{}]), Real()).unwrap()
    assert made == [] and result.step_home == "none (home: real)"


def test_c4_the_home_is_removed_when_the_call_is_refused(
    tmp_path: Path, monkeypatch
) -> None:
    exe = _tool(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    match = classify(["tool"], None, project, path_env=str(exe.parent))
    exe.write_bytes(b"second")
    homes: list[Path] = []
    real_mkdtemp = __import__("tempfile").mkdtemp

    def mkdtemp(**kw):
        homes.append(Path(real_mkdtemp(**kw)))
        return str(homes[-1])

    monkeypatch.setattr("ract.tools.command.tempfile.mkdtemp", mkdtemp)
    assert not _run(project, match, ScriptedRunner([{}])).is_ok()
    assert homes and not homes[0].exists()


def test_c5_the_fake_runner_is_a_security_variable() -> None:
    from ract.env_registry import ENV_VARS

    var = next(v for v in ENV_VARS if v.name == "RACT_FAKE_RUNNER")
    assert var.cls == "security" and "can only reduce what runs" in var.consumer


@pytest.mark.parametrize("fake", [True, False])
def test_c5_doctor_env_shows_the_runner_in_effect(
    tmp_path: Path, monkeypatch, fake: bool
) -> None:
    from ract.cli import main as cli_main

    if fake:
        monkeypatch.setenv("RACT_FAKE_RUNNER", str(tmp_path / "script.json"))
    else:
        monkeypatch.delenv("RACT_FAKE_RUNNER", raising=False)
    for args in (["doctor", "--env"], ["doctor", "--env", "--json"]):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            with contextlib.suppress(SystemExit):
                cli_main(args)
        out = buffer.getvalue()
        if "--json" in args:
            assert json.loads(out)["runner"] == ("fake" if fake else "process")
        else:
            assert ("runner: fake (RACT_FAKE_RUNNER is set)" in out) is fake
