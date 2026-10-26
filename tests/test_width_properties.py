"""Package I: property tests for the renderer's wrap path (width 20 to 200).

The renderer wraps every line it prints to its width (`PlainRenderer._fit`, and the
sanitizing output path `PlainRenderer._line`). These properties hold for any text:
no line is wider than the width in terminal columns, no text is lost or reordered,
continuation lines keep a hanging indent, a word longer than the width is split,
East Asian wide characters count as two columns, a break never separates a
combining mark from its base, and an escape byte never reaches the output.

hypothesis is a dev dependency (pyproject.toml).
"""

from __future__ import annotations

import io
import unicodedata

from hypothesis import given, settings
from hypothesis import strategies as st
from rich.cells import cell_len

from ract.session_render import PlainRenderer

WIDTHS = st.integers(min_value=20, max_value=200)
ALPHABET = st.sampled_from(
    list("abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ.,;:-_/()")
    + ["é", "ß", "ñ", "日", "本", "語", "🙂", "✓", "́", "̈", "\t"]
)
TEXT = st.text(alphabet=ALPHABET, min_size=0, max_size=400)
SETTINGS = settings(max_examples=250, deadline=None)


def _fit(text: str, width: int) -> list[str]:
    return PlainRenderer(io.StringIO().write, width=width)._fit(text)


@SETTINGS
@given(TEXT, WIDTHS)
def test_no_line_is_wider_than_the_width_in_columns(text, width):
    for line in _fit(text, width):
        assert cell_len(line) <= width, (width, line)


@SETTINGS
@given(TEXT, WIDTHS)
def test_no_text_is_lost_or_reordered(text, width):
    lines = _fit(text, width)
    rejoined = "".join("".join(line.split()) for line in lines)
    assert rejoined == "".join(text.split())


@SETTINGS
@given(TEXT, WIDTHS)
def test_continuation_lines_keep_a_hanging_indent(text, width):
    lines = _fit(text, width)
    # cell_wrap drops an indent wider than half the width to half the width.
    indent = min(len(text) - len(text.lstrip(" ")), width // 2)
    for line in lines[1:]:
        if line.strip():
            assert line.startswith(" " * indent), (indent, line)


@settings(max_examples=200, deadline=None)
@given(
    st.integers(min_value=20, max_value=200), st.integers(min_value=1, max_value=600)
)
def test_a_word_longer_than_the_width_is_split_not_overflowed(width, length):
    for line in _fit("x" * length, width):
        assert cell_len(line) <= width


@settings(max_examples=200, deadline=None)
@given(
    st.integers(min_value=20, max_value=200), st.integers(min_value=1, max_value=200)
)
def test_wide_characters_count_as_two_columns(width, count):
    for line in _fit("日" * count, width):
        assert cell_len(line) <= width, (width, line)


@SETTINGS
@given(TEXT, WIDTHS)
def test_no_continuation_line_starts_with_a_combining_mark(text, width):
    # A mark at the very start of the input has no base to attach to. Only a break
    # that separates a mark from its base is a bad break.
    for line in _fit(text, width)[1:]:
        stripped = line.lstrip(" ")
        if stripped:
            assert unicodedata.category(stripped[0]) not in {"Mn", "Mc", "Me"}, line


@SETTINGS
@given(TEXT, WIDTHS)
def test_an_escape_byte_never_reaches_the_output(text, width):
    # The escape check belongs to the output path: _line sanitizes before it wraps.
    out = io.StringIO()
    renderer = PlainRenderer(out.write, width=width)
    renderer._line(text + "\x1b[31mred\x1b[0m")
    assert "\x1b" not in out.getvalue()


def test_the_repl_folds_wide_text_by_columns(tmp_path, monkeypatch, capsys):
    # The REPL's own wrapped print (used by /mode, /cost, /permissions) counted characters too.
    from ract import cli
    from ract.repl import ReplSession
    from tests.test_repl import _Console

    monkeypatch.setenv("COLUMNS", "40")
    console = _Console()
    session = ReplSession(
        tmp_path / "ract.yaml",
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=console,
        verbs=cli.CLI_VERBS,
    )
    session._print_wrapped("日本語のテキスト" * 6)
    for line in console.lines:
        assert cell_len(line) <= 40, (cell_len(line), line)
    assert "".join(console.lines).replace("  ", "") == "日本語のテキスト" * 6


def test_the_approval_question_folds_wide_text_by_columns(monkeypatch, capsys):
    from ract.approval_callback import console_approval_callback
    from ract.manager import Step

    monkeypatch.setenv("COLUMNS", "40")
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    console_approval_callback(
        Step(action="日本語の変更を追加する", provider_hint="local", expected_artifact="src/日本語のファイル.py")
    )
    for line in capsys.readouterr().out.splitlines():
        assert cell_len(line) <= 40, (cell_len(line), line)
