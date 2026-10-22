"""The pseudo-terminal driver used for UX walkthroughs (``tests/ux``)."""

from __future__ import annotations

import sys

from tests.ux.terminal_driver import spawn, strip_ansi

PROGRAM = (
    "import sys\n"
    "print('ready', flush=True)\n"
    "line = input('name? ')\n"
    "print('hello ' + line, flush=True)\n"
    "print('tty' if sys.stdout.isatty() else 'notty', flush=True)\n"
)


def test_runs_a_program_in_a_real_terminal_and_records_timing() -> None:
    session = spawn([sys.executable, "-c", PROGRAM], cols=80, rows=24)
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
    program = (
        "import time\n"
        "print('ready', flush=True)\n"
        "try:\n"
        "    time.sleep(20)\n"
        "except KeyboardInterrupt:\n"
        "    print('caught ctrl-c', flush=True)\n"
    )
    session = spawn([sys.executable, "-c", program])
    assert session.expect("ready", 15)
    session.ctrl_c()
    assert session.expect("caught ctrl-c", 5)
    session.close(timeout=10)
