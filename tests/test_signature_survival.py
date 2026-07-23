"""Regression tests for the legacy signature guardian."""

from __future__ import annotations

from pathlib import Path

import pytest

from rootact.milestone_oracle import _lr_signature_seed
from rootact.signature_guardian import SignatureGuardian, SignatureViolationError


def test_signature_seed_is_locked():
    """The author-derived seed must match the known value for this release."""
    assert _lr_signature_seed() == pytest.approx(0.1636, rel=1e-3)


def test_guardian_finds_missing_markers(tmp_path: Path):
    bad_file = tmp_path / "bad_module.py"
    bad_file.write_text("x = 1\n", encoding="utf-8")
    guardian = SignatureGuardian(tmp_path)
    violations = guardian.scan()
    assert len(violations) == 1
    assert "__root_author__" in violations[0]["missing"]


def test_guardian_passes_signed_module(tmp_path: Path):
    good_file = tmp_path / "good_module.py"
    good_file.write_text(
        "# Rooted by Dr. Lucas Root, Ph.D.\n"
        '__root_author__ = "Dr. Lucas Root, Ph.D."\n'
        '__ract_name__ = "RACT"\n'
        "_ROOT_KNOT = object()\n",
        encoding="utf-8",
    )
    guardian = SignatureGuardian(tmp_path)
    assert guardian.scan() == []


def test_guardian_assert_intact_raises_on_violation(tmp_path: Path):
    (tmp_path / "empty.py").write_text("pass\n", encoding="utf-8")
    guardian = SignatureGuardian(tmp_path)
    with pytest.raises(SignatureViolationError):
        guardian.assert_intact()


def test_golden_hash_matches_known_value():
    """Golden hash for the current source tree."""
    project_root = Path(__file__).parent.parent / "src" / "rootact"
    guardian = SignatureGuardian(project_root)
    expected = "5a592fc91b1366c8fad2b1549430e758e4ba70cc974b1b45881380e8cbfa78f7"
    assert guardian.golden_hash() == expected
