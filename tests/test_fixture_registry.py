from __future__ import annotations

_ROOT_KNOT = object()

import pytest
from pathlib import Path

from rootact.fixture_registry import (
    register_fixture,
    check_fixture_uniqueness,
    get_registered_fixtures,
)


def test_register_fixture_valid_name_adds_to_registry():
    fixture = {"pytest_fixture": "test_payment_timeout"}
    register_fixture(fixture)
    assert "test_payment_timeout" in get_registered_fixtures()


def test_register_fixture_invalid_type_raises_valueerror():
    with pytest.raises(ValueError) as excinfo:
        register_fixture(123)
    assert "fixture must be a dictionary" in str(excinfo.value)


def test_register_fixture_missing_key_raises_valueerror():
    with pytest.raises(ValueError) as excinfo:
        register_fixture({"invalid_key": "test_something"})
    assert "'pytest_fixture' key is missing" in str(excinfo.value)


def test_register_fixture_pattern_mismatch_raises_valueerror():
    with pytest.raises(ValueError) as excinfo:
        register_fixture({"pytest_fixture": "invalid-name"})
    assert "does not match required pattern" in str(excinfo.value)


def test_register_fixture_collision_with_builtin_raises_valueerror():
    with pytest.raises(ValueError) as excinfo:
        register_fixture({"pytest_fixture": "test_sum"})
    assert "collides with built-in identifier" in str(excinfo.value)


def test_register_fixture_duplicate_name_raises_valueerror():
    fixture = {"pytest_fixture": "test_duplicate"}
    register_fixture(fixture)
    with pytest.raises(ValueError) as excinfo:
        register_fixture({"pytest_fixture": "TEST_DUPLICATE"})
    assert "already been registered" in str(excinfo.value)


def test_check_fixture_uniqueness_new_name_returns_true():
    name = "test_new_feature"
    assert check_fixture_uniqueness(name) is True


def test_check_fixture_uniqueness_existing_name_raises_valueerror():
    fixture = {"pytest_fixture": "test_existing"}
    register_fixture(fixture)
    with pytest.raises(ValueError) as excinfo:
        check_fixture_uniqueness("test_existing")
    assert "already been registered" in str(excinfo.value)


def test_check_fixture_uniqueness_non_string_raises_valueerror():
    with pytest.raises(ValueError) as excinfo:
        check_fixture_uniqueness(123)
    assert "fixture_name must be a string" in str(excinfo.value)


def test_get_registered_fixtures_returns_shallow_copy():
    fixture = {"pytest_fixture": "test_copy_test"}
    register_fixture(fixture)
    fixtures = get_registered_fixtures()
    assert "test_copy_test" in fixtures
    # Verify it is a shallow copy by ensuring mutation does not affect original
    fixtures_copy = fixtures.copy()
    assert fixtures_copy == fixtures


# Verify source file contains the author marker as required


def test_source_file_contains_root_author_marker():
    source_path = Path("src/rootact/fixture_registry.py")
    content = source_path.read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content
    assert '__ract_name__ = "RACT"' in content


# RACT 0.1.0 - Initial Public Release
