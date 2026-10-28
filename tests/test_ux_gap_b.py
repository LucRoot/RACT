"""UX gap package B: the standards that the terminal, the REPL text and the docs own.

Standard 8 (no dead ends): an unknown command suggests the nearest one.
"""

from __future__ import annotations

from pathlib import Path

from ract import cli
from ract.repl import ReplSession
from tests.test_repl import _Console


def _session(tmp_path: Path, console: _Console) -> ReplSession:
    return ReplSession(
        tmp_path / "ract.yaml",
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=console,
        verbs=cli.CLI_VERBS,
    )


def test_an_unknown_command_suggests_the_nearest_one(tmp_path):
    # Standard 8: "/hlep" should be answered with "/help", not a bare refusal.
    console = _Console()
    _session(tmp_path, console)._handle_command("/hlep")
    assert "Did you mean /help?" in console.text


def test_an_unknown_command_with_no_near_match_keeps_the_help_pointer(tmp_path):
    console = _Console()
    _session(tmp_path, console)._handle_command("/zzqxwv")
    assert "Type /help for the list." in console.text
    assert "did you mean" not in console.text


def test_the_provenance_notice_says_what_it_is_in_plain_words():
    # Standard 12: no release-status detail or project jargon in the notice.
    from ract.session_turn import provenance_notice

    text = provenance_notice(["src/calc.py", "tests/test_calc.py"])
    assert text == (
        "provenance: 2 file(s) have no signature yet (src/calc.py, tests/test_calc.py). "
        "See docs/PROVENANCE.md."
    )
    assert "Rootknot" not in text and "not wired" not in text


def test_permissions_answers_what_may_change_or_be_sent(tmp_path):
    # Standard 13: /permissions answers "what is it allowed to do" in one screen.
    console = _Console()
    session = _session(tmp_path, console)
    session.state.auto = True  # a terminal session starts in default mode (repl.py)
    session._handle_command("/permissions")
    text = console.text
    assert "Mode: default:" in text
    assert "Network:" in text and "ract.yaml" in text
    assert "Tier 3" in text and "off" in text
    assert "Sandbox:" in text and "not enforced" in text
    assert "ract trust" in text
