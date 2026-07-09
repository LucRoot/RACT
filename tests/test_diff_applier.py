# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for DiffApplier."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.diff_applier import DiffApplier


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


# RACT 0.1.1 - Trust and Tooling
