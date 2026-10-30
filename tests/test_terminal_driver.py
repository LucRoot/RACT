"""The pseudo-terminal driver used for UX walkthroughs (``tests/ux``)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from tests.ux.terminal_driver import spawn, strip_ansi

PROGRAM = (
    "import sys\n"
    "print('ready', flush=True)\n"
    "line = input('name? ')\n"
    "print('hello ' + line, flush=True)\n"
    "print('tty' if sys.stdout.isatty() else 'notty', flush=True)\n"
)


def test_runs_a_program_in_a_real_terminal_and_records_timing() -> None:
    with spawn([sys.executable, "-c", PROGRAM], cols=80, rows=24) as session:
        assert session.expect(r"name\? ", 30)
        sent = session.send_line("ract")
        assert session.expect(r"hello ract", 10)
        assert session.expect(r"\btty\b", 10)
        recording = session.close(timeout=10)
    assert recording.exit_code == 0
    first = recording.first_output_after(sent)
    assert first is not None and first < 5
    assert "hello ract" in recording.plain
    assert [e.kind for e in recording.events].count("in") == 1


def test_strip_ansi_removes_csi_osc_and_normalizes_newlines() -> None:
    raw = "\x1b]0;title\x07\x1b[1;31mred\x1b[0m\r\nnext\rline"
    assert strip_ansi(raw) == "red\nnext\nline"


def test_ctrl_c_reaches_the_child() -> None:
    # The driver used to spawn children that ignored Ctrl-C (an inherited
    # flag), which made an interrupt test pass or fail for the wrong reason.
    # "ready" is printed inside the try block: printed before it, a Ctrl-C
    # that arrives between the print and the sleep (likely under load) was
    # raised outside the handler, and the test failed in the full suite.
    program = (
        "import time\n"
        "try:\n"
        "    print('ready', flush=True)\n"
        "    time.sleep(20)\n"
        "except KeyboardInterrupt:\n"
        "    print('caught ctrl-c', flush=True)\n"
    )
    with spawn([sys.executable, "-c", program]) as session:
        assert session.expect("ready", 15)
        session.ctrl_c()
        assert session.expect("caught ctrl-c", 5)
        session.close(timeout=10)


def test_a_cursor_jump_down_is_the_blank_lines_it_replaces() -> None:
    # UX-11: ConPTY sent "b\n\n\ndef" as "b" + ESC[13;1H + "def"; the line
    # count before the jump is 10, so the jump is three line breaks.
    lines = "".join(f"line {n}\r\n" for n in range(1, 10))
    raw = lines + "    return a + b\x1b[13;1Hdef sub(a, b):"
    assert strip_ansi(raw).endswith("    return a + b\n\n\ndef sub(a, b):")


def test_a_jump_up_or_to_the_same_row_adds_nothing() -> None:
    assert strip_ansi("one\r\ntwo\x1b[1;1Hthree") == "one\ntwothree"
    # At the bottom of a scrolled screen the row stays at the height.
    scrolled = "".join(f"l{n}\r\n" for n in range(40)) + "x\x1b[30;1Hy"
    assert strip_ansi(scrolled).endswith("l39\nxy")


# --- S-020 (AUD-017): a session ends its whole process tree ---------------------


def _alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    try:
        k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(ctypes.c_void_p(handle))


def test_a_timeout_ends_the_child_and_its_children(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    program = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "print('started', flush=True)\n"
        "time.sleep(120)\n"
    )
    with spawn([sys.executable, "-c", program]) as session:
        assert session.expect("started", 30)
        grandchild = int(pid_file.read_text())
        assert _alive(grandchild)
        session.close(timeout=1)
    deadline = time.monotonic() + 10
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _alive(grandchild)


def test_with_closes_the_session_when_an_assertion_fails() -> None:
    program = "import time\nprint('up', flush=True)\ntime.sleep(120)\n"
    session = None
    with pytest.raises(AssertionError):
        with spawn([sys.executable, "-c", program]) as session:
            assert session.expect("up", 30)
            raise AssertionError("a test failed here")
    assert session is not None and not session.alive()
