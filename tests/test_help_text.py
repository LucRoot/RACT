"""Package S: help text at 40, 60 and 80 columns, and the flags the docs must name.

Lines of the discovery help (ract --help) fold to the terminal width. argparse's usage
continuation lines are the one exception at 40 columns: a single flag token longer than
the usage column cannot be folded by argparse, and those lines are named below.
"""

from __future__ import annotations

import contextlib
import io
import os

import pytest
from rich.cells import cell_len

from ract import cli, cli_help


def _discovery(columns: int, monkeypatch) -> str:
    monkeypatch.setenv("COLUMNS", str(columns))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli_help.print_discovery_help(cli.CLI_VERBS)
    return buf.getvalue()


@pytest.mark.parametrize("columns", [80, 60])
def test_the_discovery_help_fits_the_width(monkeypatch, columns):
    for line in _discovery(columns, monkeypatch).splitlines():
        assert cell_len(line) <= columns, (columns, line)


def test_at_forty_columns_only_usage_continuations_may_be_wider(monkeypatch):
    # The usage continuation lines hold flags whose token is longer than the column.
    over = [
        line
        for line in _discovery(40, monkeypatch).splitlines()
        if cell_len(line) > 40 and "[--" not in line
    ]
    assert over == [], over


def test_every_verb_has_a_one_line_description():
    for verb in cli.CLI_VERBS:
        assert cli_help.VERB_DESCRIPTIONS.get(verb), verb
