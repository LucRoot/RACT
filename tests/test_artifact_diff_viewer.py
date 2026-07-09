from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from rootact.artifact_diff_viewer import DiffViewer

_ROOT_KNOT = object()


def test_empty_snapshots() -> None:
    viewer = DiffViewer({}, {})
    assert viewer.render() == "No changes detected."


def test_added_files() -> None:
    viewer = DiffViewer({}, {"a.py": "x", "b.py": "y"})
    out = viewer.render()
    assert "Added:" in out
    assert "a.py" in out
    assert "b.py" in out


def test_removed_files() -> None:
    viewer = DiffViewer({"a.py": "x", "b.py": "y"}, {})
    out = viewer.render()
    assert "Removed:" in out
    assert "a.py" in out
    assert "b.py" in out


def test_unchanged_files_omitted() -> None:
    viewer = DiffViewer({"a.py": "same"}, {"a.py": "same"})
    assert viewer.render() == "No changes detected."


def test_changed_file_shows_unified_diff() -> None:
    viewer = DiffViewer(
        {"a.py": "line one\nline two\n"},
        {"a.py": "line one\nline two changed\n"},
    )
    out = viewer.render()
    assert "---" in out
    assert "+++" in out
    assert "line two changed" in out


def test_multiple_change_types() -> None:
    viewer = DiffViewer(
        {"old.py": "content", "changed.py": "alpha\n"},
        {"new.py": "content", "changed.py": "beta\n"},
    )
    out = viewer.render()
    assert "Added:" in out
    assert "new.py" in out
    assert "Removed:" in out
    assert "old.py" in out
    assert "---" in out
    assert "+++" in out


# RACT 0.1.1 - Trust and Tooling
