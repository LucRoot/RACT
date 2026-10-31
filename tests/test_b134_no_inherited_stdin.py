"""B-134: a test cannot read the run's stdin, and a child it starts gets end of input."""

from __future__ import annotations

import subprocess
import sys

import pytest


def test_reading_stdin_in_a_test_fails_and_says_why() -> None:
    with pytest.raises(RuntimeError, match="read the run's stdin"):
        sys.stdin.readline()
    assert sys.stdin.isatty() is False


def test_a_child_given_no_stdin_gets_end_of_input_at_once() -> None:
    done = subprocess.run(
        [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.stdout.strip() == "''"


@pytest.mark.uses_tty
def test_a_uses_tty_test_keeps_the_real_stdin() -> None:
    from tests.conftest import _NoStdin

    assert not isinstance(sys.stdin, _NoStdin)
