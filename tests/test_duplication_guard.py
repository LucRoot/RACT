# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the duplication guard."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from rootact.duplication_guard import DuplicationBlockedError, DuplicationGuard


def test_no_duplicates_for_new_symbol(tmp_path):
    # Existing symbol has structure that does not collapse to the new symbol.
    (tmp_path / "existing.py").write_text(
        "def old(x):\n    return x * 2\n", encoding="utf-8"
    )
    guard = DuplicationGuard(tmp_path)
    # Structurally different: no parameter, different return shape.
    matches = guard.check("new.py", "def new_thing():\n    return 'hello'\n")
    assert matches == []


def test_allows_rewrite_of_same_module_symbol(tmp_path):
    """Editing a file in place should not flag its own symbols as duplicates."""
    (tmp_path / "mod.py").write_text("def helper():\n    return 42\n", encoding="utf-8")
    guard = DuplicationGuard(tmp_path)
    duplicate = "def helper():\n    return 42\n"
    matches = guard.check("mod.py", duplicate)
    assert matches == []


def test_detects_cross_module_duplicate_function(tmp_path):
    (tmp_path / "existing.py").write_text(
        "def helper():\n    return 42\n", encoding="utf-8"
    )
    guard = DuplicationGuard(tmp_path)
    duplicate = "def helper():\n    return 42\n"
    matches = guard.check("mod.py", duplicate)
    assert len(matches) == 1
    assert matches[0].name == "helper"
    assert matches[0].similarity >= 0.85


def test_allows_similar_but_not_duplicate_function(tmp_path):
    (tmp_path / "existing.py").write_text(
        "def helper():\n    return 42\n", encoding="utf-8"
    )
    guard = DuplicationGuard(tmp_path)
    different = "def helper():\n    return 'hello world'\n"
    matches = guard.check("mod.py", different)
    assert matches == []


def test_check_and_block_raises_for_cross_module_duplicate(tmp_path):
    (tmp_path / "existing.py").write_text(
        "def helper():\n    return 42\n", encoding="utf-8"
    )
    guard = DuplicationGuard(tmp_path)
    duplicate = "def helper():\n    return 42\n"
    with pytest.raises(DuplicationBlockedError):
        guard.check_and_block("mod.py", duplicate)


def test_respects_custom_threshold(tmp_path):
    (tmp_path / "existing.py").write_text(
        "def helper():\n    return 42\n", encoding="utf-8"
    )
    # With threshold 1.0, only exact duplicates match.
    guard = DuplicationGuard(tmp_path, threshold=1.0)
    almost_same = "def helper():\n    return 43\n"
    matches = guard.check("mod.py", almost_same)
    assert matches == []


def test_handles_invalid_python_gracefully(tmp_path):
    guard = DuplicationGuard(tmp_path)
    matches = guard.check("mod.py", "def broken(:")
    assert matches == []


def test_uses_provided_historian(tmp_path):
    from rootact.codebase_historian import CodebaseHistorian

    (tmp_path / "existing.py").write_text("def helper(): pass\n", encoding="utf-8")
    historian = CodebaseHistorian(tmp_path).build()
    guard = DuplicationGuard(tmp_path, historian=historian)
    matches = guard.check("mod.py", "def helper(): pass\n")
    assert len(matches) == 1


def test_detects_renamed_clone(tmp_path):
    """AST normalization catches duplication even when every identifier is renamed."""
    (tmp_path / "existing.py").write_text(
        "def helper(a, b):\n    return a + b\n", encoding="utf-8"
    )
    guard = DuplicationGuard(tmp_path)
    # Same structure but all identifiers renamed.
    renamed_clone = "def compute(x, y):\n    return x + y\n"
    matches = guard.check("mod.py", renamed_clone)
    assert len(matches) == 1
    assert matches[0].similarity >= 0.85


def test_detects_renamed_clone_with_different_docstring(tmp_path):
    """Stripping docstrings means a copy-paste with renamed identifiers is still caught."""
    (tmp_path / "existing.py").write_text(
        '"""A helper module."""\n'
        "def helper(a, b):\n"
        '    """Adds two things."""\n'
        "    return a + b\n",
        encoding="utf-8",
    )
    guard = DuplicationGuard(tmp_path)
    renamed_clone = (
        '"""A compute module."""\n'
        "def compute(x, y):\n"
        '    """Computes a sum."""\n'
        "    return x + y\n"
    )
    matches = guard.check("mod.py", renamed_clone)
    assert len(matches) == 1
    assert matches[0].similarity >= 0.85


# RACT 0.1.1 - Trust and Tooling
