from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from rootact.fixture_uniquer import ensure_global_fixture_uniqueness


def test_raises_value_error_on_duplicate_fixture():
    fixtures = [
        {"pytest_fixture": "test_valid", "param1": 1},
        {"pytest_fixture": "test_valid", "param2": 2},  # duplicate name
    ]
    with pytest.raises(ValueError, match="Duplicate fixture name detected"):
        ensure_global_fixture_uniqueness(fixtures, "dummy user story")


def test_returns_new_list_with_uuid_suffixed_names():
    fixtures = [
        {"pytest_fixture": "test_valid", "param1": 1},
        {"pytest_fixture": "another_one", "param2": 2},
    ]
    result = ensure_global_fixture_uniqueness(fixtures, "dummy user story")
    assert len(result) == 2
    for fixture in result:
        name = fixture["pytest_fixture"]
        # Ensure suffix is exactly 8 hex characters
        suffix_part = name.split("_")[-1]
        assert len(suffix_part) == 8 and all(
            c in "0123456789abcdef" for c in suffix_part
        )
    # Verify original names are preserved apart from suffix
    assert result[0]["pytest_fixture"].startswith("test_valid_")
    assert result[1]["pytest_fixture"].startswith("another_one_")


def test_preserves_all_other_keys_and_values():
    fixtures = [
        {"pytest_fixture": "unique_fixture", "param_a": 42, "enabled": True},
    ]
    result = ensure_global_fixture_uniqueness(fixtures, "payment gateway failure story")
    assert len(result) == 1
    fixture = result[0]
    # All original keys must be present and unchanged except pytest_fixture
    for key, value in fixtures[0].items():
        if key != "pytest_fixture":
            assert fixture[key] == value
    # Ensure pytest_fixture has been suffixed but base name remains
    assert fixture["pytest_fixture"].startswith("unique_fixture_")


def test_validates_input_structure():
    # Missing 'pytest_fixture' key
    fixtures_missing_key = [{}]
    with pytest.raises(
        ValueError, match="Each fixture must contain a 'pytest_fixture' key"
    ):
        ensure_global_fixture_uniqueness(fixtures_missing_key, "story")

    # Non-string fixture name
    fixtures_non_string = [{"pytest_fixture": 123}]
    with pytest.raises(ValueError, match="'pytest_fixture' value must be a string"):
        ensure_global_fixture_uniqueness(fixtures_non_string, "story")

    # Not a dictionary
    fixtures_not_dict = ["not a dict"]
    with pytest.raises(ValueError, match="Each fixture must be a dictionary"):
        ensure_global_fixture_uniqueness(fixtures_not_dict, "story")
