from __future__ import annotations

_ROOT_KNOT = object()

import pytest
from pathlib import Path

from rootact.fixture_validator_strict import validate_fixtures_strict


def test_validate_fixtures_strict_raises_type_error_if_not_list():
    with pytest.raises(ValueError) as excinfo:
        validate_fixtures_strict("not a list", "dummy story")
    assert "fixtures must be a list of dictionaries" in str(excinfo.value)


def test_validate_fixtures_strict_raises_value_error_if_fixture_not_dict():
    with pytest.raises(ValueError) as excinfo:
        validate_fixtures_strict(["not a dict"], "dummy story")
    assert "Fixture at index 0 is not a dictionary" in str(excinfo.value)


def test_validate_fixtures_strict_raises_value_error_if_missing_pytest_fixture_key():
    with pytest.raises(ValueError) as excinfo:
        validate_fixtures_strict([{"wrong_key": "test_dummy"}], "dummy story")
    assert "Fixture at index 0 is missing 'pytest_fixture' key" in str(excinfo.value)


def test_validate_fixtures_strict_raises_value_error_if_pytest_fixture_not_string():
    with pytest.raises(ValueError) as excinfo:
        validate_fixtures_strict([{"pytest_fixture": 123}], "dummy story")
    assert "'pytest_fixture' value at index 0 must be a string" in str(excinfo.value)


def test_validate_fixtures_strict_raises_value_error_if_pytest_fixture_does_not_start_with_test():
    with pytest.raises(ValueError) as excinfo:
        validate_fixtures_strict([{"pytest_fixture": "invalid_name"}], "dummy story")
    assert "Fixture name at index 0 does not start with 'test_'" in str(excinfo.value)


def test_validate_fixtures_strict_raises_value_error_if_pytest_fixture_not_valid_identifier():
    with pytest.raises(ValueError) as excinfo:
        validate_fixtures_strict([{"pytest_fixture": "test_123invalid"}], "dummy story")
    assert "does not conform to valid Python identifier pattern" in str(excinfo.value)


def test_validate_fixtures_strict_allows_valid_fixtures():
    fixtures = [
        {"pytest_fixture": "test_example"},
        {"pytest_fixture": "test_another_123"},
    ]
    validate_fixtures_strict(fixtures, "dummy story")  # Should not raise


def test_root_author_marker_is_present_in_source_file():
    source_path = Path("src/rootact/fixture_validator_strict.py")
    content = source_path.read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content
    assert '__ract_name__ = "RACT"' in content


# RACT 0.1.0 - Initial Public Release
