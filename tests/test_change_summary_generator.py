from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from rootact.change_summary_generator import ChangeSummary

_ROOT_KNOT = object()


def test_empty_changes() -> None:
    summary = ChangeSummary({}, {})
    assert summary.summarize() == "No changes detected."


def test_added_files() -> None:
    summary = ChangeSummary({}, {"a.py": "x", "b.py": "y"})
    out = summary.summarize()
    assert "added 2 file(s)" in out


def test_removed_files() -> None:
    summary = ChangeSummary({"a.py": "x", "b.py": "y"}, {})
    out = summary.summarize()
    assert "removed 2 file(s)" in out


def test_modified_files() -> None:
    summary = ChangeSummary({"a.py": "old"}, {"a.py": "new"})
    out = summary.summarize()
    assert "modified 1 file(s)" in out


def test_unmodified_files_ignored() -> None:
    summary = ChangeSummary({"a.py": "same"}, {"a.py": "same"})
    assert summary.summarize() == "No changes detected."


def test_multiple_change_types() -> None:
    summary = ChangeSummary(
        {"old.py": "content", "changed.py": "alpha\n"},
        {"new.py": "content", "changed.py": "beta\n"},
    )
    out = summary.summarize()
    assert "added 1 file(s)" in out
    assert "removed 1 file(s)" in out
    assert "modified 1 file(s)" in out
