from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest
from pathlib import Path

from rootact.fixture_validator_extender import extend_fixture_validation


def test_extend_fixture_validation_raises_value_error_if_name_does_not_match_pattern():
    fixtures = {"invalid-name": lambda: None}
    with pytest.raises(ValueError) as excinfo:
        extend_fixture_validation(fixtures, None, "error")
    assert "Fixture name at index 0 does not match pattern" in str(excinfo.value)


def test_extend_fixture_validation_raises_value_error_if_fixture_not_callable():
    fixtures = {"test_valid": 123}
    with pytest.raises(ValueError) as excinfo:
        extend_fixture_validation(fixtures, None, "error")
    assert "Value for fixture 'test_valid' at index 0 is not callable" in str(
        excinfo.value
    )


def test_extend_fixture_validation_raises_assertion_error_if_substring_not_found():
    fixtures = {"test_example": lambda: None}
    with pytest.raises(AssertionError) as excinfo:
        extend_fixture_validation(fixtures, None, "expected substring")
    assert "Expected 'expected substring' not found in output" in str(excinfo.value)


def test_extend_fixture_validation_allows_valid_fixtures_without_raising():
    fixtures = {"test_example": lambda: None}
    # Should not raise for a valid fixture when no output assertion is requested.
    extend_fixture_validation(fixtures, None, "")  # noqa: F841


def test_root_author_marker_is_present_in_source_file():
    source_path = Path("src/rootact/fixture_validator_extender.py")
    content = source_path.read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content


# RACT 0.1.0 - Initial Public Release
