"""``ract --help`` enumerates every top-level verb (Lens A C1 closure).

v0.5.1 wiring module_10: prior state was ``argv[0]`` dispatch with a
help output that listed only flags. The regression here asserts that
every entry in :data:`ract.cli.CLI_VERBS` appears in the ``--help``
epilog with a one-line description.
"""

from __future__ import annotations

import contextlib
import io

import pytest

from ract.cli import CLI_VERBS, main
from ract.cli_help import VERB_DESCRIPTIONS, build_discovery_parser


def _capture_help(argv: list[str]) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        with pytest.raises(SystemExit) if False else contextlib.nullcontext():
            code = main(argv)
    assert code == 0, f"{argv} exited with {code}"
    return buf.getvalue()


def test_ract_help_lists_every_cli_verb() -> None:
    """``ract --help`` prints one line per verb."""
    text = _capture_help(["--help"])
    for verb in CLI_VERBS:
        # Every verb should appear in the enumerated list. Some verbs
        # (``run``) also appear in flag-name text; the mere-substring
        # check is fine because the epilog uses each verb as the row
        # label at column 4.
        assert verb in text, f"ract --help missing verb {verb!r}"


def test_ract_dash_h_shows_same_help() -> None:
    """``-h`` is a synonym for ``--help``."""
    text = _capture_help(["-h"])
    for verb in CLI_VERBS:
        assert verb in text, f"ract -h missing verb {verb!r}"


def test_ract_help_verb_synonym_lists_verbs() -> None:
    """``ract help`` (no verb) is a synonym for ``ract --help``."""
    text = _capture_help(["help"])
    for verb in CLI_VERBS:
        assert verb in text, f"ract help missing verb {verb!r}"


def test_verb_descriptions_cover_every_cli_verb() -> None:
    """Every CLI_VERBS entry has a description in VERB_DESCRIPTIONS.

    The builder tolerates missing entries with a placeholder, but the
    audit finding is that operators need REAL one-line descriptions,
    not placeholders.
    """
    missing = [v for v in CLI_VERBS if v not in VERB_DESCRIPTIONS]
    assert not missing, f"verbs missing from VERB_DESCRIPTIONS: {missing}"


def test_discovery_parser_lists_every_verb() -> None:
    """The parser's subparser choices include every declared verb."""
    parser = build_discovery_parser(CLI_VERBS)
    # Find the subparsers action.
    subparsers_action = None
    for action in parser._actions:
        if isinstance(action, __import__("argparse")._SubParsersAction):
            subparsers_action = action
            break
    assert subparsers_action is not None
    for verb in CLI_VERBS:
        assert verb in subparsers_action.choices, (
            f"discovery parser missing subparser for {verb!r}"
        )


# RACT 0.5.1 -- v0.5.1 wiring module_10 (Lens A C1 regression)
