"""B-179 first slice: named colour styles, off without a terminal or with NO_COLOR; the words stay."""

from __future__ import annotations

import re

import pytest

from ract.ui.colour import STYLES, colour_on, model_text, paint

ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


@pytest.mark.parametrize(
    ("env", "is_terminal", "expected"),
    [
        ({}, True, True),
        ({}, False, False),
        ({"NO_COLOR": "1"}, True, False),
        ({"NO_COLOR": ""}, True, True),  # an empty value counts as unset
        ({"NO_COLOR": "   "}, True, True),
        ({"NO_COLOR": "0"}, True, False),  # any value turns colour off
    ],
)
def test_colour_is_on_only_for_a_terminal_without_no_color(
    env, is_terminal, expected
) -> None:
    assert colour_on(env, is_terminal) is expected


def test_paint_is_the_same_text_when_colour_is_off() -> None:
    for style in STYLES:
        assert paint("the plan", style, on=False) == "the plan"


def test_stripping_the_codes_gives_the_plain_text() -> None:
    for style in STYLES:
        styled = paint("tests passed", style, on=True)
        assert ESCAPE.sub("", styled) == "tests passed"
        assert styled != "tests passed"


def test_an_unknown_style_is_plain_even_with_colour_on() -> None:
    assert paint("x", "neon", on=True) == "x"


def test_every_style_is_one_of_the_sixteen_basic_colours_or_an_attribute() -> None:
    for code in STYLES.values():
        assert code in {"30", "31", "32", "33", "34", "35", "36", "37", "1", "2"}


def test_model_text_never_carries_a_raw_escape_when_colour_is_off() -> None:
    text = model_text("run \x1b[31mred\x07", on=False)
    assert "\x1b" not in text and "\x07" not in text
    assert "\\x1b" in text and "\\x07" in text


def test_model_text_with_colour_has_only_the_style_codes_as_escapes() -> None:
    styled = model_text("hello \x1b[31m", on=True)
    assert (
        styled.count("\x1b") == 2
    )  # the dim code and its reset; the model's own escape is shown as text
    assert "\\x1b" in styled
