"""Package S: help text at 40, 60 and 80 columns, and the flags the docs must name.

Lines of the discovery help (ract --help) fold to the terminal width. argparse's usage
continuation lines are the one exception at 40 columns: a single flag token longer than
the usage column cannot be folded by argparse, and those lines are named below.
"""

from __future__ import annotations

import contextlib
import io

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


def test_every_verb_help_ends_with_its_one_example(capsys):
    from ract.cli_examples import VERB_EXAMPLES

    for verb in ("run", "doctor", "undo"):
        capsys.readouterr()
        code = cli.main([verb, "--help"])
        out = capsys.readouterr().out
        assert code == 0
        assert out.rstrip("\n").endswith(f"example:\n  {VERB_EXAMPLES[verb]}"), out[
            -200:
        ]


def test_each_example_names_a_verb_and_flags_the_parser_accepts():
    # The flags come from the verb's own --help (or its subcommand's), not from the table,
    # which keeps only the first command that accepts each flag.
    from docs import flags_table
    from ract.cli_examples import VERB_EXAMPLES

    for verb, example in VERB_EXAMPLES.items():
        assert verb in cli.CLI_VERBS, verb
        words = example.split()
        assert words[0] == "ract" and words[1] == verb, example
        verb_help = flags_table._help_text([verb])
        subs = flags_table._subcommands(verb_help)
        scope_text = verb_help
        if len(words) > 2 and words[2] in subs:
            scope_text = flags_table._help_text([verb, words[2]])
        accepted = {flag for flag, _ in flags_table._options(scope_text)}
        flags = {word for word in words if word.startswith("--")}
        assert flags <= accepted, (verb, sorted(flags - accepted))
