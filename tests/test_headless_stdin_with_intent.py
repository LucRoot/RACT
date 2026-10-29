"""B-093 (D-102): `ract -p` with an open stdin does not hang unannounced.

Adjudication row 16: with an intent on the command line and stdin inherited from
a parent that never closes it, the run waited without a word. Now piped stdin is
read until it closes, a notice goes to stderr after a few seconds of nothing, and
a stdin that sends nothing for the idle timeout ends the run with exit 2 and a
hint naming ``--no-stdin``. Data that keeps arriving is read to the end.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ract import headless


class _OpenStdin:
    """Stands in for an inherited stdin: not a terminal, and a read that would block."""

    def __init__(self) -> None:
        self.reads = 0

    def isatty(self) -> bool:
        return False

    def read(self) -> str:
        self.reads += 1
        return ""


def test_no_stdin_skips_the_read(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    stdin = _OpenStdin()
    err = io.StringIO()
    code = headless.run_headless(
        ["-p", "add a greeting", "--no-stdin", "--config", "missing.yaml"],
        stdin=stdin,
        stdout=io.StringIO(),
        stderr=err,
    )
    assert stdin.reads == 0
    # The flag was accepted: the run got as far as the missing configuration.
    assert code == 2 and "configuration file not found" in err.getvalue()


def test_no_intent_and_no_stdin_is_a_usage_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    err = io.StringIO()
    code = headless.run_headless(
        ["-p", "--no-stdin"], stdin=_OpenStdin(), stdout=io.StringIO(), stderr=err
    )
    assert code == 2 and "no prompt" in err.getvalue()


def _pipe() -> tuple[int, int]:
    read_fd, write_fd = os.pipe()
    return read_fd, write_fd


def test_piped_data_with_an_intent_is_context() -> None:
    read_fd, write_fd = _pipe()
    os.write(write_fd, b"the log says x\n")
    os.close(write_fd)
    with os.fdopen(read_fd, "r", encoding="utf-8") as stdin:
        piped = headless._read_stdin(stdin, idle_timeout=5)
    assert piped == "the log says x\n"
    assert headless.build_prompt("explain", piped).endswith(
        "<stdin>\nthe log says x\n</stdin>"
    )


def test_data_that_keeps_arriving_is_read_to_the_end() -> None:
    # The card's case (a byte every 10 s for 60 s, timeout 30 s) scaled down:
    # a byte every 0.4 s for 3.2 s with a 1 s idle timeout. The timer restarts
    # on every byte, so the total time is never a limit.
    read_fd, write_fd = _pipe()

    def writer() -> None:
        for _ in range(8):
            time.sleep(0.4)
            os.write(write_fd, b"x")
        os.close(write_fd)

    thread = threading.Thread(target=writer)
    thread.start()
    with os.fdopen(read_fd, "r", encoding="utf-8") as stdin:
        piped = headless._read_stdin(stdin, idle_timeout=1.0)
    thread.join()
    assert piped == "x" * 8


def test_the_override_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(headless.IDLE_TIMEOUT_ENV, "1.5")
    assert headless._idle_timeout() == 1.5
    for bad in ("0", "-3", "soon"):
        monkeypatch.setenv(headless.IDLE_TIMEOUT_ENV, bad)
        assert headless._idle_timeout() == headless.IDLE_TIMEOUT
    monkeypatch.delenv(headless.IDLE_TIMEOUT_ENV)
    assert headless._idle_timeout() == 30.0


def test_the_notice_and_the_stall_go_to_stderr_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(headless, "NOTICE_AFTER", 0.3)
    monkeypatch.setenv(headless.IDLE_TIMEOUT_ENV, "1")
    read_fd, write_fd = _pipe()
    out, err = io.StringIO(), io.StringIO()
    try:
        with os.fdopen(read_fd, "r", encoding="utf-8") as stdin:
            code = headless.run_headless(
                ["-p", "add a greeting", "--config", "missing.yaml"],
                stdin=stdin,
                stdout=out,
                stderr=err,
            )
    finally:
        os.close(write_fd)
    assert code == 2
    assert out.getvalue() == ""
    text = err.getvalue()
    assert text.count("waiting for stdin to close") == 1
    assert "--no-stdin" in text and "RACT_STDIN_IDLE_TIMEOUT" in text


def test_a_real_run_with_an_open_stdin_exits_2(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env["RACT_STDIN_IDLE_TIMEOUT"] = "2"
    started = time.monotonic()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "-p",
            "add a greeting",
            "--config",
            "x.yaml",
        ],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        out, err = _wait(proc)
    finally:
        if proc.stdin is not None:
            proc.stdin.close()
    assert proc.returncode == 2, err
    assert out == ""
    assert "--no-stdin" in err
    assert time.monotonic() - started < 30


def _wait(proc: subprocess.Popen) -> tuple[str, str]:
    """Wait for the process while its stdin stays open (communicate would close it)."""
    deadline = time.monotonic() + 60
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    if proc.poll() is None:
        proc.kill()
    out = proc.stdout.read() if proc.stdout else ""
    err = proc.stderr.read() if proc.stderr else ""
    return out, err
