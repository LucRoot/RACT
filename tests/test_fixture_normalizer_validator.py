from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from rootact.fixture_normalizer_validator import (
    validate_and_normalize_fixtures,
    _ROOT_KNOT,
)


def test_raises_value_error_on_non_list_input():
    with pytest.raises(ValueError, match="fixtures must be a list of dictionaries"):
        validate_and_normalize_fixtures("not a list", "user story")


def test_raises_value_error_on_missing_pytest_fixture_key():
    fixtures = [{}]
    with pytest.raises(
        ValueError, match="Fixture at index 0 is missing 'pytest_fixture' key"
    ):
        validate_and_normalize_fixtures(fixtures, "user story")


def test_raises_value_error_on_non_string_pytest_fixture():
    fixtures = [{"pytest_fixture": 123}]
    with pytest.raises(
        ValueError, match="'pytest_fixture' value at index 0 must be a string"
    ):
        validate_and_normalize_fixtures(fixtures, "user story")


def test_raises_value_error_on_uppercase_or_spaces():
    fixtures = [
        {"pytest_fixture": "test_InvalidName"},
        {"pytest_fixture": "test_Another Invalid"},
    ]
    with pytest.raises(ValueError, match="contains uppercase letters or spaces"):
        validate_and_normalize_fixtures(fixtures, "user story")


def test_raises_value_error_on_pattern_mismatch():
    fixtures = [{"pytest_fixture": "invalid_test_name"}]
    with pytest.raises(
        ValueError, match=r"does not match pattern 'test_\[a-z_\]\[a-z0-9_\]\*'"
    ):
        validate_and_normalize_fixtures(fixtures, "user story")


def test_raises_value_error_on_duplicate_names():
    fixtures = [{"pytest_fixture": "test_a"}, {"pytest_fixture": "test_a"}]
    with pytest.raises(ValueError, match="Duplicate fixture name found"):
        validate_and_normalize_fixtures(fixtures, "user story")


def test_raises_value_error_on_collision_with_builtin():
    fixtures = [{"pytest_fixture": "test_sum"}]  # 'sum' is a built-in name
    with pytest.raises(ValueError, match="collides with built-in identifier"):
        validate_and_normalize_fixtures(fixtures, "user story")


def test_returns_new_list_with_unique_suffixed_names():
    fixtures = [{"pytest_fixture": "test_example"}, {"pytest_fixture": "test_another"}]
    result = validate_and_normalize_fixtures(fixtures, "user story")
    assert len(result) == 2
    for fixture in result:
        assert "pytest_fixture" in fixture
        name = fixture["pytest_fixture"]
        assert name.startswith("test_example_") or name.startswith("test_another_")
        assert len(name.rsplit("_", 1)[-1]) == 8
    # Ensure original list is not mutated
    assert fixtures[0]["pytest_fixture"] == "test_example"


def test_imports_root_knot_from_source_module():
    # Verify that the test imports _ROOT_KNOT from the source module, not redefining it
    import rootact.fixture_normalizer_validator as mod

    assert hasattr(mod, "_ROOT_KNOT")
    assert mod._ROOT_KNOT is _ROOT_KNOT


# RACT 0.1.0 - Initial Public Release
