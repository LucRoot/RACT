"""UX gap package A: the REPL's multi-line commands fit the terminal width.

Every command that prints more than one line is run at 60 and at 40 columns
through a real Rich console, and no line of its output may be wider than the
width. The terminal is a dumb one (TERM=dumb), where Rich falls back to 80 columns.
The commands are the REPL's own table entries that run without a model.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from ract import cli
from ract.repl import ReplSession
from ract.tui import RactConsole
from tests.ux.run_baseline import _configure

MULTI_LINE = [
    "help",
    "settings",
    "context",
    "sessions",
    "cost",
    "mode",
    "model",
    "providers",
]


class _Capture(RactConsole):
    """A RactConsole whose output goes to a buffer with the same rules as a terminal."""

    def __init__(self) -> None:
        super().__init__()
        self.buffer = io.StringIO()
        self._console = Console(
            file=self.buffer,
            color_system=None,
            force_terminal=True,
            highlight=False,
            soft_wrap=True,
            legacy_windows=False,
        )


def _session(tmp_path: Path, console: RactConsole) -> ReplSession:
    config = tmp_path / "ract.yaml"
    _configure(tmp_path, "http://127.0.0.1:9", "fake-coder")
    return ReplSession(
        config,
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=console,
        verbs=cli.CLI_VERBS,
    )


@pytest.mark.parametrize("columns", [60, 40])
@pytest.mark.parametrize("name", MULTI_LINE)
def test_a_multi_line_command_fits_the_terminal_width(
    tmp_path, monkeypatch, columns, name
):
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("COLUMNS", str(columns))
    console = _Capture()
    session = _session(tmp_path, console)
    assert name in session._builtins
    session._builtins[name]([])
    lines = console.buffer.getvalue().splitlines()
    assert lines, f"/{name} printed nothing"
    too_wide = [line for line in lines if len(line) > columns]
    assert too_wide == [], f"/{name} at {columns} columns: {too_wide[:2]}"


def test_help_at_forty_columns_keeps_both_columns_readable(tmp_path, monkeypatch):
    # The table is drawn to the terminal width, not the 80-column default.
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("COLUMNS", "40")
    console = _Capture()
    session = _session(tmp_path, console)
    session._builtins["help"]([])
    text = console.buffer.getvalue()
    assert "Command" in text and "What it does" in text
    assert "/cost" in text
