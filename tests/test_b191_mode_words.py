"""B-191: each mode word has one meaning, and every text says which setting it is.

``/mode`` sets how file changes are handled (plan, default, auto-accept, with
the aliases ask, accept-edits and edits); ``/permissions ask|allowlist`` sets
how tier-3 commands are handled. ``/set auto on`` selected the mode that asks,
the opposite of ``/mode auto-accept``: it is retired and says what to type.
``/set mode`` (default, documentation, git) read like ``/mode``: it is now
``/set task``, and the old name still works for now.
"""

from __future__ import annotations

import pytest

from tests.test_repl import _session

FILE_CHANGE_WORDS = {
    "plan": "File changes: plan:",
    "default": "File changes: default:",
    "ask": "File changes: default:",
    "auto-accept": "File changes: auto-accept:",
    "accept-edits": "File changes: auto-accept:",
    "edits": "File changes: auto-accept:",
}


@pytest.mark.parametrize(("word", "shown"), FILE_CHANGE_WORDS.items())
def test_every_mode_word_is_a_file_change_mode(
    word: str, shown: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    session, _calls, console = _session()
    session.handle(f"/mode {word}")
    assert shown in console.text
    assert "Tier-3" not in console.text


def test_the_tier_3_ask_word_names_tier_3() -> None:
    session, _calls, console = _session()
    session._set_tier3_mode("ask")
    assert "Tier-3 commands: ask:" in console.text
    assert "File changes" not in console.text


def test_set_auto_is_retired_and_changes_nothing() -> None:
    session, calls, console = _session()
    before = vars(session.state).copy()
    session.handle("/set auto on")
    assert vars(session.state) == before and calls == []
    assert "/mode default asks before each change" in console.text
    assert "/mode auto-accept applies changes" in console.text


def test_set_task_sets_the_task_mode_and_set_mode_still_works() -> None:
    session, _calls, console = _session()
    session.handle("/set task git")
    assert session.state.mode == "git"
    session.handle("/set mode documentation")
    assert session.state.mode == "documentation"
    assert "/set mode is now /set task" in console.text
