"""S-027: a Ctrl-C pressed just before a console read starts is raised, not held until Enter.

The window is the time ``input()`` spends writing its prompt before
ReadConsoleW starts; a 100 KB prompt widens it enough to hit it on purpose
(plain ``input()`` held 9 of 30 presses that way; ``read_line`` none).
"""

from __future__ import annotations

import builtins
import os
import sys
import time

import pytest

from ract import console_interrupt
from tests.ux.terminal_driver import spawn

windows = pytest.mark.skipif(
    os.name != "nt", reason="the hold is a Windows console behavior"
)

_CHILD = (
    "import sys\n"
    "from ract.console_interrupt import read_line\n"
    "try:\n"
    "    print('ready', flush=True)\n"
    "    read_line('x' * int(sys.argv[1]) + '> ')\n"
    "    print('read-returned', flush=True)\n"
    "except KeyboardInterrupt:\n"
    "    print('interrupted', flush=True)\n"
)


@windows
def test_a_ctrl_c_before_the_read_starts_is_not_held() -> None:
    held = []
    for delay_ms in [0, 1, 2, 5, 10, 20] * 2:
        with spawn(
            [sys.executable, "-c", _CHILD, "100000"], cols=80, rows=24
        ) as session:
            assert session.expect("ready", 30)
            time.sleep(delay_ms / 1000)
            session.ctrl_c()
            if not session.expect("interrupted", 2.0):
                held.append(delay_ms)
                session.send_line("")
            session.close(timeout=5)
    assert not held, f"Ctrl-C held until Enter after {held} ms"


@windows
def test_a_line_typed_at_the_prompt_is_read() -> None:
    with spawn([sys.executable, "-c", _CHILD, "0"], cols=80, rows=24) as session:
        assert session.expect("ready", 30)
        session.send_line("hello")
        assert session.expect("read-returned", 10)


@windows
def test_a_ctrl_c_during_one_read_leaves_the_next_read_alone() -> None:
    child = (
        "from ract.console_interrupt import read_line\n"
        "try:\n"
        "    read_line('first> ')\n"
        "except KeyboardInterrupt:\n"
        "    print('first-interrupted', flush=True)\n"
        "print('second: ' + read_line('second> '), flush=True)\n"
    )
    with spawn([sys.executable, "-c", child], cols=80, rows=24) as session:
        assert session.expect("first>", 30)
        time.sleep(0.2)
        session.ctrl_c()
        assert session.expect("first-interrupted", 5)
        assert session.expect("second>", 5)
        time.sleep(0.2)  # longer than the 30 ms the guard waits before cancelling
        session.send_line("kept")
        assert session.expect("second: kept", 10)


def test_read_line_reads_through_builtins_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Tests patch builtins.input; the default `ask` of trust and setup is read_line now.
    monkeypatch.setattr(builtins, "input", lambda prompt="": f"typed after {prompt}")
    assert console_interrupt.read_line("q? ") == "typed after q? "


def test_a_ctrl_c_with_no_read_in_progress_is_left_to_python() -> None:
    console_interrupt._note_ctrl_c()  # nothing to cancel, nothing kept
    assert console_interrupt._reading["n"] == 0
