from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from rootact.fixture_output_validator_extender import (
    _ROOT_KNOT,
    extend_fixture_validation,
)


def test_extend_validation_accepts_valid_fixtures(capsys):
    """Valid fixture names and present substring should pass."""

    def good_fixture() -> None:
        print("expected error substring here")

    fixtures = {"test_good": good_fixture}
    extend_fixture_validation(fixtures, capsys, "expected error substring")


def test_extend_validation_rejects_invalid_name(capsys):
    """A fixture name not matching '^test_[a-z][a-z0-9_]*$' should raise ValueError."""

    def fixture() -> None:
        print("expected error substring")

    fixtures = {"bad_name": fixture}
    with pytest.raises(ValueError, match="does not match pattern"):
        extend_fixture_validation(fixtures, capsys, "expected error substring")


def test_extend_validation_rejects_non_callable(capsys):
    """A non-callable value should raise ValueError."""
    fixtures = {"test_not_callable": "not a function"}
    with pytest.raises(ValueError, match="is not callable"):
        extend_fixture_validation(fixtures, capsys, "expected error substring")


def test_extend_validation_rejects_missing_substring(capsys):
    """Absent substring in output should raise AssertionError."""

    def quiet_fixture() -> None:
        print("unexpected content")

    fixtures = {"test_quiet": quiet_fixture}
    with pytest.raises(AssertionError, match="not found in captured output"):
        extend_fixture_validation(fixtures, capsys, "missing substring")


def test_root_author_marker_is_present():
    from pathlib import Path

    source = Path("src/rootact/fixture_output_validator_extender.py").read_text(
        encoding="utf-8"
    )
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in source


def test_root_knot_is_imported_from_source():
    assert _ROOT_KNOT is not None


# RACT 0.1.0 - Initial Public Release
