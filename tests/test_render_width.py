"""B-041c: the session renderer takes the terminal's width (40 to 80 columns).

The checklist and the diff block are drawn by the renderer, so the width it
gets is the width they fit. A narrow terminal gets narrow lines.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract import cli
from ract.repl import ReplSession


class _Console:
    def print(self, *args, **kwargs) -> None:
        pass

    info = success = warning = error = print


def _session(tmp_path: Path) -> ReplSession:
    return ReplSession(
        tmp_path / "ract.yaml",
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=_Console(),
        verbs=cli.CLI_VERBS,
    )


@pytest.mark.parametrize(
    "columns, expected",
    [("60", 60), ("30", 40), ("200", 80), ("40", 40)],
)
def test_the_render_width_follows_the_terminal(
    tmp_path, monkeypatch, columns, expected
):
    monkeypatch.setenv("COLUMNS", columns)
    assert _session(tmp_path)._render_width() == expected


def test_a_long_renderer_line_is_wrapped_to_the_width_with_a_hanging_indent():
    # B-041c: the plan's assumption and the turn summary's long lines fit the width.
    import io

    from ract.session_render import PlainRenderer

    out = io.StringIO()
    renderer = PlainRenderer(out.write, width=60)
    renderer._line(
        "  assumes: " + "the planner assumed a long thing about the module " * 3
    )
    lines = out.getvalue().splitlines()
    assert len(lines) > 1
    assert all(len(line) <= 60 for line in lines), lines
    assert lines[1].startswith("  ")


def test_the_approval_prompt_wraps_to_the_terminal_width(monkeypatch, capsys):
    # B-041c: the approval question fits the terminal; its answer stays on the last line.
    from ract import approval_callback

    class _Step:
        provider_hint = "local"
        action = (
            "Add tests/test_notes.py that checks NOTE across two modules and the parser"
        )
        expected_artifact = "tests/test_notes.py"
        tool_call = None

    monkeypatch.setenv("COLUMNS", "60")
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert approval_callback.console_approval_callback(_Step()) is True
    out = capsys.readouterr().out
    assert out and all(len(line) <= 60 for line in out.splitlines()), out


def test_the_renderer_and_the_approval_prompt_hold_to_forty_columns(
    monkeypatch, capsys
):
    import io

    from ract import approval_callback
    from ract.session_render import PlainRenderer

    out = io.StringIO()
    renderer = PlainRenderer(out.write, width=40)
    renderer._line(
        "  assumes: " + "the planner assumed a long thing about the module " * 3
    )
    assert all(len(line) <= 40 for line in out.getvalue().splitlines())

    class _Step:
        provider_hint = "local"
        action = "Add tests/test_notes.py that checks NOTE across two modules"
        expected_artifact = "tests/test_notes.py"
        tool_call = None

    monkeypatch.setenv("COLUMNS", "40")
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    approval_callback.console_approval_callback(_Step())
    shown = capsys.readouterr().out
    assert shown and all(len(line) <= 40 for line in shown.splitlines()), shown
