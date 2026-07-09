# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the refactor tax ledger."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.refactor_ledger import RefactorLedger


def test_new_file_counts_as_added():
    ledger = RefactorLedger(project_dir=None)  # type: ignore[arg-type]
    ledger.record_file_changes({"foo.py": (None, "line1\nline2\n")})
    assert ledger.lines_added == 2
    assert ledger.maintained_lines == 0
    assert ledger.is_breach() is True


def test_deleted_file_counts_as_removed():
    ledger = RefactorLedger(project_dir=None)  # type: ignore[arg-type]
    ledger.record_file_changes({"foo.py": ("old\nstuff\n", None)})
    assert ledger.lines_removed == 2
    assert ledger.lines_added == 0
    assert ledger.is_breach() is False


def test_modification_with_net_addition():
    ledger = RefactorLedger(project_dir=None)  # type: ignore[arg-type]
    ledger.record_file_changes({"foo.py": ("a\nb\n", "a\nb\nc\n")})
    assert ledger.lines_added == 1
    assert ledger.lines_refactored == 2
    assert ledger.ratio == 0.5
    assert ledger.is_breach() is False


def test_modification_with_net_removal():
    ledger = RefactorLedger(project_dir=None)  # type: ignore[arg-type]
    ledger.record_file_changes({"foo.py": ("a\nb\nc\n", "a\nb\n")})
    assert ledger.lines_removed == 1
    assert ledger.lines_refactored == 2
    assert ledger.lines_added == 0
    assert ledger.is_breach() is False


def test_breach_when_only_adding():
    ledger = RefactorLedger(project_dir=None, threshold=3.0)  # type: ignore[arg-type]
    ledger.record_file_changes({"foo.py": (None, "1\n2\n3\n4\n5\n6\n7\n")})
    assert ledger.lines_added == 7
    assert ledger.maintained_lines == 0
    assert ledger.is_breach() is True


def test_allow_debt_overrides_breach():
    ledger = RefactorLedger(project_dir=None, threshold=3.0)  # type: ignore[arg-type]
    ledger.record_file_changes({"foo.py": (None, "1\n2\n3\n4\n5\n6\n7\n")})
    ledger.allow_debt("pure feature addition is intentional")
    assert ledger.is_breach() is False
    assert ledger.override_reason == "pure feature addition is intentional"


def test_ratio_below_threshold_is_not_breach():
    ledger = RefactorLedger(project_dir=None, threshold=3.0)  # type: ignore[arg-type]
    ledger.record_file_changes(
        {
            "foo.py": ("old\nline\n", "new\nline\nextra\n"),
        }
    )
    # added 1, refactored 2 -> ratio 0.5
    assert ledger.ratio == 0.5
    assert ledger.is_breach() is False


def test_ratio_above_threshold_is_breach():
    ledger = RefactorLedger(project_dir=None, threshold=1.0)  # type: ignore[arg-type]
    ledger.record_file_changes(
        {
            "foo.py": ("old\nline\n", "old\nline\nadd1\nadd2\nadd3\n"),
        }
    )
    # added 3, refactored 2 -> ratio 1.5 > 1.0
    assert ledger.ratio == 1.5
    assert ledger.is_breach() is True


def test_save_and_load(tmp_path):
    ledger = RefactorLedger(project_dir=tmp_path, threshold=2.0)
    ledger.record_file_changes({"foo.py": (None, "one\ntwo\n")})
    path = ledger.save(session_id="sess-1")
    assert path.is_file()

    loaded = RefactorLedger.load(tmp_path)
    assert loaded.threshold == 2.0
    assert loaded.lines_added == 2
    assert loaded.lines_removed == 0
    assert loaded.lines_refactored == 0


def test_load_missing_returns_fresh_ledger(tmp_path):
    ledger = RefactorLedger.load(tmp_path)
    assert ledger.lines_added == 0
    assert ledger.lines_removed == 0
    assert ledger.lines_refactored == 0


def test_dict_snapshot():
    ledger = RefactorLedger(project_dir=None, threshold=3.0)  # type: ignore[arg-type]
    ledger.record_file_changes({"foo.py": ("a\n", "a\nb\n")})
    snapshot = ledger.to_dict()
    assert snapshot["lines_added"] == 1
    assert snapshot["lines_refactored"] == 1
    assert snapshot["ratio"] == 1.0
    assert snapshot["breach"] is False


# RACT 0.1.1 - Trust and tooling
