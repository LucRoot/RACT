"""B-185: a message is text: brackets are shown, never read as Rich markup.

``RactConsole.info/success/warning/error/direct/user_input`` interpolated the
message into markup: "[line 3, column 2]" and "[draft]" were deleted, and
"[/bold]" raised MarkupError, which killed the turn's thread when it came from
the error handler in ``repl.py``.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from ract.tui import RactConsole

MESSAGES = [
    "parse error [line 3, column 2] in C:/proj/[draft]/ract.yaml",
    "x [/bold] y",
    "[red]not red[/red] and [link=https://example.invalid]no link[/link]",
]


def _console() -> tuple[RactConsole, io.StringIO]:
    out = io.StringIO()
    console = RactConsole()
    plain = Console(file=out, width=200, color_system=None, force_terminal=False)
    console._console = plain
    console._stderr_console = plain  # error() writes to stderr
    return console, out


@pytest.mark.parametrize("message", MESSAGES)
@pytest.mark.parametrize("method", ["info", "success", "warning", "error", "direct"])
def test_every_console_method_shows_the_brackets(method: str, message: str) -> None:
    console, out = _console()
    getattr(console, method)(message)
    assert message in out.getvalue()


@pytest.mark.parametrize("message", MESSAGES)
def test_user_input_shows_label_and_value_as_text(message: str) -> None:
    console, out = _console()
    console.user_input(message, message)
    assert out.getvalue().count(message) == 2
