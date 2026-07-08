from __future__ import annotations

_ROOT_KNOT = object()

import pytest

from rootact.fixture_validator_extended import validate_and_normalize_fixtures_extended


def test_raises_value_error_on_uppercase_or_spaces() -> None:
    fixtures = [{"pytest_fixture": "Test_Foo"}, {"pytest_fixture": "test_bar"}]
    with pytest.raises(ValueError) as excinfo:
        validate_and_normalize_fixtures_extended(fixtures, "user story")
    assert "uppercase letters or spaces" in str(excinfo.value)


def test_raises_value_error_on_pattern_mismatch() -> None:
    fixtures = [
        {"pytest_fixture": "test_invalid-name"},
        {"pytest_fixture": "test_valid"},
    ]
    with pytest.raises(ValueError) as excinfo:
        validate_and_normalize_fixtures_extended(fixtures, "user story")
    assert "does not match pattern" in str(excinfo.value)


def test_raises_value_error_on_duplicate_names() -> None:
    fixtures = [{"pytest_fixture": "test_a"}, {"pytest_fixture": "test_a"}]
    with pytest.raises(ValueError) as excinfo:
        validate_and_normalize_fixtures_extended(fixtures, "user story")
    assert "Duplicate fixture name found" in str(excinfo.value)


def test_raises_value_error_on_collision_with_builtin() -> None:
    fixtures = [
        {"pytest_fixture": "test_str"},
        {"pytest_fixture": "test_list"},
    ]  # 'str' and 'list' are built-ins
    with pytest.raises(ValueError) as excinfo:
        validate_and_normalize_fixtures_extended(fixtures, "user story")
    assert "collides with built-in identifier" in str(excinfo.value)


def test_raises_value_error_on_keyword() -> None:
    fixtures = [
        {"pytest_fixture": "test_if"},
        {"pytest_fixture": "test_for"},
    ]  # 'if' and 'for' are keywords
    with pytest.raises(ValueError) as excinfo:
        validate_and_normalize_fixtures_extended(fixtures, "user story")
    assert "Python keyword" in str(excinfo.value)


def test_returns_new_list_with_uuid_suffixes() -> None:
    fixtures = [{"pytest_fixture": "test_a"}, {"pytest_fixture": "test_b"}]
    result = validate_and_normalize_fixtures_extended(fixtures, "user story")
    assert len(result) == 2
    for fixture in result:
        assert "_" in fixture["pytest_fixture"]
        parts = fixture["pytest_fixture"].rsplit("_", 1)
        assert len(parts) == 2
        suffix = parts[1]
        assert len(suffix) == 8
        assert all(c in "0123456789abcdef" for c in suffix)
    # Ensure original fixture dicts are not mutated
    assert fixtures[0]["pytest_fixture"] != result[0]["pytest_fixture"]


def test_imports_root_knot_from_source() -> None:
    """Verify that tests read the __root_author__ marker from the source file."""
    import pathlib

    src_path = (
        pathlib.Path(__file__).parents[1]
        / "src"
        / "rootact"
        / "fixture_validator_extended.py"
    )
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in src_path.read_text()
    assert '__ract_name__ = "RACT"' in src_path.read_text()


# RACT 0.1.0 - Initial Public Release
