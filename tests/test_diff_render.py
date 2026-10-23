"""B-014a: the diff hunk renderer is a pure function of two texts.

Failure cases first. The renderer draws changes; it never reads a file.
"""

from __future__ import annotations

import random
import re
import time

import pytest

from ract.diff_render import render_hunks, summarize

BODY = re.compile(r"^ *\d+ ([ +-]) (.*)$")


def _body(lines: list[str]) -> list[tuple[str, str]]:
    """(marker, text) for each gutter line, in order."""
    return [(m.group(1), m.group(2)) for m in (BODY.match(x) for x in lines) if m]


def _apply(old: str, lines: list[str]) -> str:
    """Rebuild the new text from the context and '+' lines of a rendered diff.

    Hunks are rendered in order and cover the whole change, so the lines
    between hunks are context that the test does not need to see.
    """
    old_lines = old.split("\n")
    out: list[str] = []
    cursor = 0
    for marker, text in _body(lines):
        if marker == " ":
            out.append(text)
            cursor += 1
        elif marker == "-":
            cursor += 1
        elif marker == "+":
            out.append(text)
    tail = old_lines[cursor:]
    return "\n".join(out + tail)


# -- nothing changed


def test_empty_and_identical_texts_draw_nothing():
    assert render_hunks("a.py", "", "") == []
    assert render_hunks("a.py", "x\ny\n", "x\ny\n") == []
    assert summarize([("a.py", 0, 0)]) == "no changes"


# -- one change, and where it sits


def test_one_line_change_in_the_middle_has_a_header_and_context():
    old = "a\nb\nc\nd\ne\n"
    new = "a\nb\nX\nd\ne\n"
    lines = render_hunks("src/calc.py", old, new)
    assert lines[0] == "src/calc.py: lines 1-5 -> 1-5, +1 -1"
    assert _body(lines) == [
        (" ", "a"),
        (" ", "b"),
        ("-", "c"),
        ("+", "X"),
        (" ", "d"),
        (" ", "e"),
    ]


def test_change_at_the_start_and_at_the_end_of_a_file():
    start = render_hunks("f.py", "a\nb\n", "A\nb\n")
    assert ("-", "a") in _body(start) and ("+", "A") in _body(start)
    end = render_hunks("f.py", "a\nb\n", "a\nB\n")
    assert ("-", "b") in _body(end) and ("+", "B") in _body(end)


def test_no_newline_at_end_of_file_is_said_in_words():
    lines = render_hunks("f.py", "a\nb", "a\nB")
    assert any("no newline at end of file" in line for line in lines)


# -- hunks and their distance


def test_two_changes_far_apart_make_two_headers():
    old = "".join(f"line {i}\n" for i in range(1, 31))
    new = old.replace("line 2\n", "two\n").replace("line 28\n", "twenty-eight\n")
    lines = render_hunks("f.py", old, new)
    headers = [line for line in lines if ": lines " in line]
    assert len(headers) == 2


def test_two_changes_within_the_context_distance_make_one_hunk():
    old = "".join(f"line {i}\n" for i in range(1, 11))
    new = old.replace("line 4\n", "four\n").replace("line 6\n", "six\n")
    lines = render_hunks("f.py", old, new)
    headers = [line for line in lines if ": lines " in line]
    assert len(headers) == 1


# -- kinds of file


def test_new_file_lists_its_first_twenty_lines_as_additions():
    body = "".join(f"n{i}\n" for i in range(25))
    lines = render_hunks("new.py", None, body)
    assert lines[0] == "new.py: new file, 25 lines"
    assert len(_body(lines)) == 20
    assert all(marker == "+" for marker, _ in _body(lines))
    assert lines[-1] == "... 5 more lines"


def test_deleted_file_lists_its_first_twenty_lines_as_removals():
    body = "".join(f"d{i}\n" for i in range(3))
    lines = render_hunks("gone.py", body, None)
    assert lines[0] == "gone.py: deleted file, 3 lines"
    assert all(marker == "-" for marker, _ in _body(lines))


def test_binary_file_has_no_hunks():
    lines = render_hunks("img.bin", "a\x00b", "a\x00c")
    assert lines == ["img.bin: binary file, 3 bytes"]


def test_crlf_only_change_is_described_not_drawn():
    lines = render_hunks("f.txt", "a\r\nb\r\n", "a\nb\n")
    assert lines == ["f.txt: line endings changed (CRLF to LF)"]


def test_a_real_edit_in_a_crlf_file_shows_only_the_edit():
    lines = render_hunks("f.txt", "a\r\nb\r\nc\r\n", "a\r\nB\r\nc\r\n")
    assert lines[0] == "f.txt: lines 1-3 -> 1-3, +1 -1"
    assert _body(lines) == [(" ", "a"), ("-", "b"), ("+", "B"), (" ", "c")]


def test_mixed_endings_that_differ_only_in_endings_are_described():
    lines = render_hunks("f.txt", "a\r\nb\nc\r\n", "a\nb\r\nc\n")
    assert lines == ["f.txt: line endings changed (mixed)"]


# -- hostile text


def test_a_long_line_is_cut_to_the_width_with_the_line_count_unchanged():
    short = render_hunks("f.py", "a\nb\n", "a\nB\n", width=80)
    long_text = "x" * 10_000
    cut = render_hunks("f.py", "a\nb\n", f"a\n{long_text}\n", width=80)
    assert len(cut) == len(short)
    assert all(len(line) <= 80 for line in cut)
    assert any(line.endswith("...") for line in cut)


def test_escape_bell_bidi_and_nul_never_reach_the_output():
    hostile = "red \x1b[31mred\x07 ‮flip\x00end"
    lines = render_hunks("f.py", "a\n", f"{hostile}\n")
    text = "\n".join(lines)
    for bad in ("\x1b", "\x07", "\x00", "‮"):
        assert bad not in text


# -- limits and widths


def test_max_lines_cuts_and_counts_the_rest():
    old = "".join(f"o{i}\n" for i in range(100))
    new = "".join(f"n{i}\n" for i in range(100))
    lines = render_hunks("f.py", old, new, max_lines=10)
    assert len(lines) == 11
    assert lines[-1].startswith("... ") and lines[-1].endswith(" more lines")
    total = len(render_hunks("f.py", old, new, max_lines=10_000))
    assert lines[-1] == f"... {total - 10} more lines"


def test_no_line_is_wider_than_forty_or_eighty():
    old = "a\n" + "b" * 300 + "\n"
    new = "a\n" + "c" * 300 + "\n"
    for width in (40, 80):
        for line in render_hunks("f.py", old, new, width=width):
            assert len(line) <= width


def test_gutter_aligns_for_files_of_nine_ten_ninety_nine_hundred_and_thousand_lines():
    for count in (9, 10, 99, 100, 1000):
        old = "".join(f"o{i}\n" for i in range(count))
        new = old[:-3] + "X\n"
        width = len(str(count))
        body = [line for line in render_hunks("f.py", old, new) if BODY.match(line)]
        assert body
        for line in body:
            gutter = line[:width]
            assert gutter.strip() == "" or gutter.strip().isdigit()
            assert line[width] == " "
            assert line[width + 1] in " +-"


# -- round trip


def test_applying_rendered_lines_to_the_old_text_gives_the_new_text():
    rng = random.Random(20261022)
    for _ in range(10):
        old_lines = [f"w{rng.randrange(1000)}" for _ in range(rng.randrange(5, 40))]
        new_lines = list(old_lines)
        for _ in range(rng.randrange(1, 4)):
            index = rng.randrange(len(new_lines))
            choice = rng.random()
            if choice < 0.4:
                new_lines[index] = f"e{rng.randrange(1000)}"
            elif choice < 0.7:
                new_lines.insert(index, f"i{rng.randrange(1000)}")
            elif len(new_lines) > 1:
                del new_lines[index]
        old = "\n".join(old_lines) + "\n"
        new = "\n".join(new_lines) + "\n"
        # One hunk that holds the whole file, so no lines are left out between hunks.
        rendered = render_hunks(
            "f.py", old, new, width=1000, context=1000, max_lines=100_000
        )
        if old == new:
            assert rendered == []
            continue
        assert _apply(old, rendered) == new


def test_a_pair_over_the_line_cap_returns_at_once_with_the_count_only():
    # G-117: difflib is quadratic on repetitive input. Past the cap the module
    # must not call it; it says the line counts it can know cheaply.
    old = "}\n" * 20_000
    new = "}\n" * 20_001
    started = time.perf_counter()
    lines = render_hunks("gen.js", old, new)
    assert time.perf_counter() - started < 1.0
    assert lines == [
        "gen.js: file too large to draw a diff: 20000 -> 20001 lines; +1 -0 by line count"
    ]


@pytest.mark.parametrize("count", [1_000, 5_000, 8_000])
def test_repetitive_input_at_each_size_returns_within_two_seconds(count):
    # G-117 / reviewer: difflib is slow on repetitive lines. Each size must return
    # inside a generous bound; the bound is loose because CI boxes are slow.
    old = "}\n" * count
    new = "}\n" * (count - 1) + "x\n"
    started = time.perf_counter()
    lines = render_hunks("gen.js", old, new)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"{count} lines took {elapsed:.2f} s"
    assert lines


def test_a_pair_at_the_cap_still_draws_its_change():
    old = "".join(f"line {i}\n" for i in range(5_000))
    new = old.replace("line 2500\n", "changed\n")
    lines = render_hunks("big.py", old, new)
    assert any(": lines " in line for line in lines)


def test_output_is_deterministic():
    old = "a\nb\nc\n"
    new = "a\nB\nc\nd\n"
    assert render_hunks("f.py", old, new) == render_hunks("f.py", old, new)


# -- summary


def test_summary_counts_files_and_lines():
    assert summarize([("src/calc.py", 1, 1)]) == "1 file, +1 -1"
    assert summarize([("a.py", 2, 0), ("b.py", 1, 3)]) == "2 files, +3 -3"


def test_one_inserted_line_in_repetitive_input_is_counted_exactly():
    # G-130: with autojunk, a repetitive file once showed +1250 -1250 for one line.
    old = "}\n" * 2_500
    new = "}\n" * 1_250 + "x\n" + "}\n" * 1_250
    lines = render_hunks("gen.js", old, new)
    assert lines[0].endswith("+1 -0")
    hunks = [line for line in lines if ": lines " in line]
    assert len(hunks) == 1
    body = [line for line in lines if BODY.match(line)]
    assert len(body) <= 7


def test_a_changed_line_among_repetitive_lines_is_visible_early():
    old = "}\n" * 3_000
    new = "}\n" * 1_500 + "x\n" + "}\n" * 1_499
    lines = render_hunks("gen.js", old, new)
    assert any(marker == "+" for marker, _ in _body(lines[:200]))


def test_five_thousand_repetitive_lines_finish_under_one_second():
    old = "}\n" * 5_000
    new = "}\n" * 4_999 + "x\n"
    started = time.perf_counter()
    lines = render_hunks("gen.js", old, new)
    assert time.perf_counter() - started < 1.0
    assert lines
