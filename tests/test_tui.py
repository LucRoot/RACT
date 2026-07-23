# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the RACT terminal UI helpers."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import os
from unittest.mock import MagicMock, patch

from ract.tui import RactConsole, _reconfigure_utf8


def test_reconfigure_utf8_swallows_exception() -> None:
    stream = MagicMock()
    stream.reconfigure.side_effect = OSError("no")
    with patch("ract.tui.sys.stdout", stream):
        _reconfigure_utf8()


def test_console_property_returns_console() -> None:
    rc = RactConsole()
    assert rc.console is rc._console


def test_no_color_disables_color_system() -> None:
    with patch.dict(os.environ, {"NO_COLOR": "1"}):
        rc = RactConsole()
        assert rc._console.color_system is None


def test_info_prints_branded_message(capsys) -> None:
    rc = RactConsole()
    rc.info("hello")
    out = capsys.readouterr().out
    assert "hello" in out


def test_success_prints_checkmark(capsys) -> None:
    rc = RactConsole()
    rc.success("done")
    out = capsys.readouterr().out
    assert "done" in out


def test_warning_prints_symbol(capsys) -> None:
    rc = RactConsole()
    rc.warning("careful")
    out = capsys.readouterr().out
    assert "careful" in out


def test_error_goes_to_stderr(capsys) -> None:
    rc = RactConsole()
    rc.error("boom")
    err = capsys.readouterr().err
    assert "boom" in err


def test_user_input_highlights_value(capsys) -> None:
    rc = RactConsole()
    rc.user_input("Intent", "build tests")
    out = capsys.readouterr().out
    assert "build tests" in out


def test_direct_prints_message(capsys) -> None:
    rc = RactConsole()
    rc.direct("starting loop")
    out = capsys.readouterr().out
    assert "starting loop" in out


def test_panel_renders_with_default_style(capsys) -> None:
    rc = RactConsole()
    rc.panel("Title", "body content")
    out = capsys.readouterr().out
    assert "Title" in out
    assert "body content" in out


def test_rule_renders(capsys) -> None:
    rc = RactConsole()
    rc.rule("section")
    out = capsys.readouterr().out
    assert "section" in out


def test_table_renders_rows(capsys) -> None:
    rc = RactConsole()
    rc.table("My Table", ["a", "b"], [["1", "2"], ["3", "4"]])
    out = capsys.readouterr().out
    assert "My Table" in out
    assert "1" in out


def test_welcome_renders_logo_and_body(capsys) -> None:
    rc = RactConsole()
    rc.welcome("0.1.0")
    out = capsys.readouterr().out
    assert "Root Knot" in out
    assert "0.1.0" in out
    assert "Dr. Lucas Root" in out


# RACT 0.1.1 - Trust and tooling
