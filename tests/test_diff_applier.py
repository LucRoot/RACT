"""Tests for DiffApplier."""

from __future__ import annotations


import pytest

from ract.diff_applier import DiffApplier


def test_apply_simple_diff(tmp_path):
    target = tmp_path / "foo.py"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")
    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-line2\n"
        "+line2_changed\n"
        " line3\n"
    )
    applier = DiffApplier(tmp_path)
    results = applier.apply_diff(diff)
    assert len(results) == 1
    assert results[0].applied is True
    assert "line2_changed" in target.read_text(encoding="utf-8")


def test_apply_diff_missing_file(tmp_path):
    diff = "diff --git a/missing.py b/missing.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"
    applier = DiffApplier(tmp_path)
    results = applier.apply_diff(diff)
    assert results[0].applied is False


def test_restore_from_backup(tmp_path):
    target = tmp_path / "foo.py"
    target.write_text("original\n", encoding="utf-8")
    diff = "diff --git a/foo.py b/foo.py\n@@ -1,1 +1,1 @@\n-original\n+changed\n"
    applier = DiffApplier(tmp_path)
    results = applier.apply_diff(diff)
    backup = results[0].backup
    assert backup is not None
    assert applier.restore(backup, target)
    assert target.read_text(encoding="utf-8") == "original\n"


def test_apply_diff_preserves_no_trailing_newline(tmp_path):
    target = tmp_path / "foo.py"
    target.write_bytes(b"line1\nline2")
    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "@@ -1,2 +1,2 @@\n"
        " line1\n"
        "-line2\n"
        "+line2_changed\n"
    )
    applier = DiffApplier(tmp_path)
    results = applier.apply_diff(diff)
    assert results[0].applied is True
    content = target.read_bytes()
    assert content == b"line1\nline2_changed"


def test_apply_diff_preserves_trailing_newline(tmp_path):
    target = tmp_path / "foo.py"
    target.write_bytes(b"line1\nline2\n")
    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "@@ -1,2 +1,2 @@\n"
        " line1\n"
        "-line2\n"
        "+line2_changed\n"
    )
    applier = DiffApplier(tmp_path)
    results = applier.apply_diff(diff)
    assert results[0].applied is True
    content = target.read_bytes()
    assert content == b"line1\nline2_changed\n"


# RACT 0.1.1 - Trust and tooling


# S-021: inside a hunk, "--- " and "+++ " are content unless they open the
# next file ("--- ", "+++ ", "@@"). Hunk counts do not decide (G-034).


def test_removed_sql_comment_line_is_not_a_header(tmp_path):
    target = tmp_path / "schema.sql"
    target.write_text(
        "-- old comment\nCREATE TABLE t (id INT);\nSELECT 1;\n", encoding="utf-8"
    )
    diff = (
        "--- a/schema.sql\n"
        "+++ b/schema.sql\n"
        "@@ -1,3 +1,3 @@\n"
        "--- old comment\n"
        "+-- new comment\n"
        " CREATE TABLE t (id INT);\n"
        "-SELECT 1;\n"
        "+SELECT 2;\n"
    )
    results = DiffApplier(tmp_path).apply_diff(diff)
    assert [r.applied for r in results] == [True], [r.message for r in results]
    assert target.read_text(encoding="utf-8") == (
        "-- new comment\nCREATE TABLE t (id INT);\nSELECT 2;\n"
    )


def test_added_line_starting_with_plus_plus_space_is_content(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("a\nb\n", encoding="utf-8")
    diff = "--- a/notes.txt\n+++ b/notes.txt\n@@ -1,2 +1,3 @@\n a\n+++ counter\n b\n"
    results = DiffApplier(tmp_path).apply_diff(diff)
    assert [r.applied for r in results] == [True]
    assert target.read_text(encoding="utf-8") == "a\n++ counter\nb\n"


def test_lua_comment_and_a_second_file_after_the_hunk(tmp_path):
    lua = tmp_path / "init.lua"
    lua.write_text("-- setup\nlocal x = 1\n", encoding="utf-8")
    other = tmp_path / "b.txt"
    other.write_text("one\n", encoding="utf-8")
    diff = (
        "--- a/init.lua\n+++ b/init.lua\n"
        "@@ -1,2 +1,2 @@\n--- setup\n+-- set up\n local x = 1\n"
        "--- a/b.txt\n+++ b/b.txt\n"
        "@@ -1 +1 @@\n-one\n+two\n"
    )
    results = DiffApplier(tmp_path).apply_diff(diff)
    assert [r.applied for r in results] == [True, True]
    assert lua.read_text(encoding="utf-8") == "-- set up\nlocal x = 1\n"
    assert other.read_text(encoding="utf-8") == "two\n"


@pytest.mark.parametrize(
    "header",
    [
        "@@ -1,3 +1,3 @@",  # correct
        "@@ -1,2 +1,2 @@",  # too small
        "@@ -1,9 +1,9 @@",  # too large
        "@@ -1,4 +1,4 @@",  # too large by one
    ],
)
def test_wrong_hunk_counts_still_apply_both_files(tmp_path, header):
    """G-034: models miscount hunks; a count must not decide where a hunk
    ends. With a too-large count the count-based parser applied no file."""
    a = tmp_path / "a.py"
    a.write_text("x1\nx2\nx3\n", encoding="utf-8")
    b = tmp_path / "b.py"
    b.write_text("one\n", encoding="utf-8")
    diff = (
        "--- a/a.py\n+++ b/a.py\n"
        f"{header}\n x1\n-x2\n+y2\n x3\n"
        "--- a/b.py\n+++ b/b.py\n"
        "@@ -1 +1 @@\n-one\n+two\n"
    )
    results = DiffApplier(tmp_path).apply_diff(diff)
    assert [r.applied for r in results] == [True, True], [r.message for r in results]
    assert a.read_text(encoding="utf-8") == "x1\ny2\nx3\n"
    assert b.read_text(encoding="utf-8") == "two\n"


def test_a_hunk_that_ends_early_then_a_header(tmp_path):
    a = tmp_path / "a.sql"
    a.write_text("-- head\nSELECT 1;\nSELECT 2;\n", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("one\n", encoding="utf-8")
    diff = (
        "--- a/a.sql\n+++ b/a.sql\n"
        "@@ -1,3 +1,3 @@\n--- head\n+-- top\n"  # says 3 lines, has 2
        "--- a/b.txt\n+++ b/b.txt\n@@ -1 +1 @@\n-one\n+two\n"
    )
    results = DiffApplier(tmp_path).apply_diff(diff)
    assert [r.applied for r in results] == [True, True], [r.message for r in results]
    assert a.read_text(encoding="utf-8").startswith("-- top\n")
    assert b.read_text(encoding="utf-8") == "two\n"


def test_a_lookalike_header_pair_inside_a_hunk_is_content(tmp_path):
    """A removed "-- a" and an added "++ b" read as "--- a" and "+++ b". They
    are content because no "@@" follows them. Known limit: the same pair
    followed directly by a hunk header would be read as a file header."""
    target = tmp_path / "notes.txt"
    target.write_text("-- a\nkeep\n", encoding="utf-8")
    diff = "--- a/notes.txt\n+++ b/notes.txt\n@@ -1,2 +1,2 @@\n--- a\n+++ b\n keep\n"
    results = DiffApplier(tmp_path).apply_diff(diff)
    assert [r.applied for r in results] == [True], [r.message for r in results]
    assert target.read_text(encoding="utf-8") == "++ b\nkeep\n"
