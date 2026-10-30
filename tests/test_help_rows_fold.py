"""G-196: every /help command cell folds at a space at 40 columns.

At 40 columns the command column holds 16 characters; a longer word is split
in the middle ("purpose|step|rol" / "e]"). Long option lists go into the
description instead.
"""

from __future__ import annotations

from ract.repl import HELP_ROWS

COMMAND_COLUMN_AT_40 = 16


def test_no_word_in_the_command_column_is_wider_than_it_is_at_40_columns() -> None:
    long_words = [
        (command, word)
        for command, _ in HELP_ROWS
        for word in command.split()
        if len(word) > COMMAND_COLUMN_AT_40
    ]
    assert not long_words, long_words


def test_the_options_moved_to_the_descriptions_are_still_named() -> None:
    rows = dict(HELP_ROWS)
    assert "--by purpose, step or role" in rows["/cost [--by KEY]"]
    assert "--check-providers" in rows["/doctor [OPTIONS]"]
    assert "auto-accept" in rows["/mode [MODE]"]
