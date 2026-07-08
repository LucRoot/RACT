from __future__ import annotations

_ROOT_KNOT = object()

import pytest
from pathlib import Path

from rootact.fixture_namer_normalizer import normalize_pytest_fixture_names


def test_normalize_pytest_fixture_names_raises_value_error_if_not_list():
    with pytest.raises(ValueError) as excinfo:
        normalize_pytest_fixture_names("not a list", "dummy story")
    assert "fixtures must be a list of dictionaries" in str(excinfo.value)


def test_normalize_pytest_fixture_names_raises_value_error_if_fixture_not_dict():
    with pytest.raises(ValueError) as excinfo:
        normalize_pytest_fixture_names(["not a dict"], "dummy story")
    assert "Fixture at index 0 is not a dictionary" in str(excinfo.value)


def test_normalize_pytest_fixture_names_raises_value_error_if_missing_pytest_fixture_key():
    with pytest.raises(ValueError) as excinfo:
        normalize_pytest_fixture_names([{"wrong_key": "test_dummy"}], "dummy story")
    assert "Fixture at index 0 is missing 'pytest_fixture' key" in str(excinfo.value)


def test_normalize_pytest_fixture_names_raises_value_error_if_pytest_fixture_not_string():
    with pytest.raises(ValueError) as excinfo:
        normalize_pytest_fixture_names([{"pytest_fixture": 123}], "dummy story")
    assert "'pytest_fixture' value at index 0 must be a string" in str(excinfo.value)


def test_normalize_pytest_fixture_names_raises_value_error_if_pytest_fixture_does_not_start_with_test():
    with pytest.raises(ValueError) as excinfo:
        normalize_pytest_fixture_names(
            [{"pytest_fixture": "invalid_name"}], "dummy story"
        )
    assert "Fixture name at index 0 does not start with 'test_'" in str(excinfo.value)


def test_normalize_pytest_fixture_names_raises_value_error_if_pytest_fixture_not_valid_identifier():
    with pytest.raises(ValueError) as excinfo:
        normalize_pytest_fixture_names(
            [{"pytest_fixture": "test_123invalid"}], "dummy story"
        )
    assert "does not conform to valid Python identifier pattern" in str(excinfo.value)


def test_normalize_pytest_fixture_names_allows_valid_fixtures():
    fixtures = [
        {"pytest_fixture": "test_example"},
        {"pytest_fixture": "test_another_123"},
    ]
    result = normalize_pytest_fixture_names(fixtures, "dummy story")
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["pytest_fixture"] == "test_example"
    assert result[1]["pytest_fixture"] == "test_another_123"


def test_root_author_marker_is_present_in_source_file():
    source_path = Path("src/rootact/fixture_namer_normalizer.py")
    content = source_path.read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content
    assert '__ract_name__ = "RACT"' in content
