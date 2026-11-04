"""The ``!`` shell escape (CLI_EXPECTATIONS.md row 2, operator ruling 2026-11-03).

A line that starts with ``!`` runs as a command the OPERATOR typed, with the
operator's authority: the model never reaches this path, nothing is planned,
no grant is involved (the keystrokes are the consent). Output and the exit
code are shown plainly; where the machine cannot confine commands the line
says so, as everywhere else in RACT.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_repl import _session  # noqa: E402


def _ready(tmp_path):
    (tmp_path / "ract.yaml").write_text("project:\n  name: t\n", encoding="utf-8")
    return _session(config=tmp_path / "ract.yaml")


def test_a_bang_line_runs_as_a_command_and_never_reaches_the_model(tmp_path, capsys):
    session, calls, console = _ready(tmp_path)

    assert session.handle("!echo hello-ract") is True

    assert "hello-ract" in capsys.readouterr().out
    assert "exit 0" in console.text
    # The intent path (and therefore the model) never saw the line.
    assert calls == []


def test_a_failing_command_says_so(tmp_path, capsys):
    session, _, console = _ready(tmp_path)

    assert session.handle("!exit 3") is True

    assert "exit 3" in console.text


def test_a_bang_with_nothing_after_it_prints_usage(tmp_path, capsys):
    session, calls, console = _ready(tmp_path)

    assert session.handle("!") is True

    assert "!" in console.text and "command" in console.text
    assert calls == []


def test_the_command_runs_in_the_project_folder(tmp_path, capsys):
    session, _, _ = _ready(tmp_path)

    assert session.handle("!cd") if sys.platform == "win32" else session.handle("!pwd")

    shown = capsys.readouterr().out.lower().replace("/", "\\")
    assert str(tmp_path).lower().replace("/", "\\") in shown
