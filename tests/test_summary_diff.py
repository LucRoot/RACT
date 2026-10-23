"""B-014b: the turn summary's diff block, drawn from (path, before, after) inputs.

The harness wiring is waiting for an ESCALATE answer; these tests cover the
pure drawing, which takes its inputs directly.
"""

from __future__ import annotations

import time

from ract.diff_render import draw_turn_diff


def test_a_one_line_edit_gives_one_hunk_and_the_total():
    lines = draw_turn_diff([("src/calc.py", "a\nb\nc\n", "a\nB\nc\n")])
    assert lines[0] == "src/calc.py: lines 1-3 -> 1-3, +1 -1"
    assert lines[-1] == "1 file, +1 -1"


def test_a_new_and_a_deleted_file_show_their_one_line_forms():
    lines = draw_turn_diff([("new.py", None, "x\ny\n"), ("gone.py", "p\n", None)])
    assert "new.py: new file, 2 lines" in lines
    assert "gone.py: deleted file, 1 line" in lines
    assert lines[-1] == "2 files, +2 -1"


def test_a_binary_file_and_a_crlf_only_change_are_one_line_each():
    lines = draw_turn_diff(
        [("img.bin", "a\x00b", "a\x00c"), ("doc.txt", "a\r\nb\r\n", "a\nb\n")]
    )
    assert "img.bin: binary file, 3 bytes" in lines
    assert "doc.txt: line endings changed (CRLF to LF)" in lines


def test_a_turn_that_changed_nothing_draws_nothing():
    assert draw_turn_diff([]) == []
    assert draw_turn_diff([("same.py", "a\n", "a\n")]) == []


def test_twelve_changed_files_show_the_first_files_and_say_how_many_are_left():
    changes = []
    for number in range(12):
        old = "".join(f"line {i}\n" for i in range(20))
        new = old.replace("line 5\n", f"five {number}\n")
        changes.append((f"src/mod{number:02d}.py", old, new))
    lines = draw_turn_diff(changes)
    assert len(lines) <= 60 + 1
    assert any(line.startswith("... and ") and "more files" in line for line in lines)
    assert lines[-1] == "12 files, +12 -12"


def test_a_long_turn_stops_at_sixty_lines_and_says_how_many_are_left():
    old = "".join(f"o{i}\n" for i in range(200))
    new = "".join(f"n{i}\n" for i in range(200))
    lines = draw_turn_diff([("big.py", old, new)])
    body = [line for line in lines if not line.startswith("1 file")]
    assert len(body) <= 60
    assert any(line.startswith("... ") and "more lines" in line for line in lines)
    assert all("/diff" not in line for line in lines)


def test_hostile_content_is_clean_and_bounded():
    hostile = "x" * 10_000 + "\x1b[2J‮\x07"
    lines = draw_turn_diff([("evil.py", "a\n", hostile + "\n")], width=60)
    text = "\n".join(lines)
    for bad in ("\x1b", "\x07", "‮"):
        assert bad not in text
    assert all(len(line) <= 60 for line in lines)


def test_a_twenty_thousand_line_file_gives_a_summary_in_under_a_second():
    old = "}\n" * 20_000
    new = "}\n" * 19_999 + "x\n"
    started = time.perf_counter()
    lines = draw_turn_diff([("gen.js", old, new)])
    assert time.perf_counter() - started < 1.0
    assert lines[-1].endswith(("+1 -1", "by line count", "-0"))


def test_header_shaped_text_in_a_file_never_changes_the_totals():
    # G-152: the totals come from the hunk data, never from matching rendered text.
    old = "a = 0\n"
    new = "# x: lines 1-2, +99 -99\n# y: new file, 500 lines\n"
    lines = draw_turn_diff([("calc.py", old, new)])
    assert lines[-1] == "1 file, +2 -1"
