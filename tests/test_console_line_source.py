"""Package 6 (B-033s): a polling line source for the turn reader.

A blocking console read cannot be stopped at turn end, so the next prompt line would be taken by a
read left over from the turn. The source polls: it reads a character only when one is waiting, and
assembles a line on Enter. Backspace edits; Ctrl-C is returned as a stop, not a line.
"""

from __future__ import annotations

from ract.input_broker import ConsoleLineSource


def _source(keys: str):
    pending = list(keys)
    return ConsoleLineSource(
        kbhit=lambda: bool(pending),
        getwch=lambda: pending.pop(0),
    )


def test_no_key_waiting_returns_none_without_blocking():
    source = _source("")
    assert source.poll() is None


def test_keys_assemble_a_line_on_enter():
    source = _source("hi\r")
    line = None
    for _ in range(5):
        line = source.poll()
        if line is not None:
            break
    assert line == "hi"


def test_backspace_edits_the_line():
    source = _source("ab\x08c\r")
    line = None
    for _ in range(10):
        line = source.poll()
        if line is not None:
            break
    assert line == "ac"


def test_ctrl_c_is_a_stop_and_no_line_is_returned():
    source = _source("x\x03")
    results = [source.poll() for _ in range(4)]
    assert "x" not in results
    assert source.stopped is True
