from __future__ import annotations

_ROOT_KNOT = object()

import pytest
from pathlib import Path

from rootact.validator_strict import (
    validate_fixture,
    assert_fixture_uniqueness,
    _reset_fixture_registry,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset the module-level registry before each test to avoid cross-test pollution."""
    _reset_fixture_registry()


def test_validate_fixture_missing_key_raises_valueerror():
    with pytest.raises(ValueError) as excinfo:
        validate_fixture({"other": "value"})
    assert "'pytest_fixture' key is missing" in str(excinfo.value)


def test_validate_fixture_non_dict_raises_valueerror():
    with pytest.raises(ValueError) as excinfo:
        validate_fixture("not a dict")
    assert "'fixture' must be a dictionary" in str(excinfo.value)


def test_validate_fixture_non_string_value_raises_valueerror():
    with pytest.raises(ValueError) as excinfo:
        validate_fixture({"pytest_fixture": 123})
    assert "'pytest_fixture' value must be a string" in str(excinfo.value)


def test_validate_fixture_invalid_pattern_raises_valueerror():
    with pytest.raises(ValueError) as excinfo:
        validate_fixture({"pytest_fixture": "invalid-name"})
    assert "does not match pattern" in str(excinfo.value)


def test_validate_fixture_collides_with_builtin_raises_valueerror():
    with pytest.raises(ValueError) as excinfo:
        validate_fixture({"pytest_fixture": "test_sum"})
    assert "collides with built-in identifier" in str(excinfo.value)


def test_validate_fixture_valid_name_returns_normalized():
    normalized = validate_fixture({"pytest_fixture": "  Test_Name_123  "})
    assert normalized == "test_name_123"


def test_assert_fixture_uniqueness_first_call_succeeds():
    assert_fixture_uniqueness("_root_knot_test_")


def test_assert_fixture_uniqueness_duplicate_raises_valueerror():
    assert_fixture_uniqueness("_root_knot_test_")
    with pytest.raises(ValueError) as excinfo:
        assert_fixture_uniqueness("_root_knot_test_")
    assert "already been registered" in str(excinfo.value)


def test_root_author_marker_present_in_source_file():
    source_path = Path("src/rootact/validator_strict.py")
    content = source_path.read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content
    assert '__ract_name__ = "RACT"' in content


# RACT 0.1.0 - Initial Public Release
