"""Whether an approval question is open on the terminal (adjudication row 5).

An interim mark, until the input design (B-033s) owns this. The approval prompt
sets it while it waits for the operator's answer; the plain renderer holds its
heartbeat lines while it is set, so a tick never prints onto the question's line.
Pure state: no import from the input handling or the event layer.
"""

from __future__ import annotations

import threading

_open = threading.Event()


def open_question() -> None:
    """Mark that an approval question is waiting for an answer."""
    _open.set()


def close_question() -> None:
    """Clear the mark once the answer has been read (or the read failed)."""
    _open.clear()


def question_open() -> bool:
    """True while an approval question is waiting for an answer."""
    return _open.is_set()
