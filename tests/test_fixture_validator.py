from __future__ import annotations

_ROOT_KNOT = object()

import pytest
from pathlib import Path

from rootact.fixture_validator import validate_generated_fixtures


def test_validate_generated_fixtures_all_valid_returns_true():
    fixtures = [
        {
            "scenario": "network timeout",
            "pytest_fixture": "test_network_timeout",
            "assertion": "assert response['status'] == 200 and 'timeout' not in response['body']",
        },
        {
            "scenario": "invalid currency code",
            "pytest_fixture": "test_invalid_currency",
            "assertion": "assert 'currency' in mock_response and mock_response['currency'] == 'USD'",
        },
    ]
    user_story = "Payment gateway timed out after 30 seconds."
    assert validate_generated_fixtures(fixtures, user_story) is True


def test_validate_generated_fixtures_invalid_input_type_raises():
    with pytest.raises(TypeError):
        validate_generated_fixtures("not a list", "any string")


def test_validate_generated_fixtures_non_dict_elements_raise():
    fixtures = [
        "not a dict",
        {"scenario": "x", "pytest_fixture": "x", "assertion": "assert True"},
    ]
    with pytest.raises(TypeError):
        validate_generated_fixtures(fixtures, "test")


def test_validate_generated_fixtures_pytest_fixture_not_string():
    fixtures = [{"scenario": "x", "pytest_fixture": 123, "assertion": "assert True"}]
    with pytest.raises(TypeError):
        validate_generated_fixtures(fixtures, "test")


def test_validate_generated_fixtures_pytest_fixture_invalid_pattern():
    fixtures = [
        {"scenario": "x", "pytest_fixture": "123invalid", "assertion": "assert True"}
    ]
    assert validate_generated_fixtures(fixtures, "test") is False


def test_validate_generated_fixtures_assertion_not_start_with_assert():
    fixtures = [{"scenario": "x", "pytest_fixture": "fx", "assertion": "True"}]
    assert validate_generated_fixtures(fixtures, "test") is False


def test_validate_generated_fixtures_undefined_variable_in_assertion():
    fixtures = [
        {
            "scenario": "x",
            "pytest_fixture": "fx",
            "assertion": "assert undefined_var > 0",
        }
    ]
    assert validate_generated_fixtures(fixtures, "test") is False


def test_validate_generated_fixtures_assertion_raises_during_eval():
    fixtures = [
        {
            "scenario": "x",
            "pytest_fixture": "fx",
            "assertion": "assert len(missing_key) > 0",
        }
    ]
    assert validate_generated_fixtures(fixtures, "test") is False


def test_root_author_marker_present_in_source_file():
    source_path = Path("src/rootact/fixture_validator.py")
    content = source_path.read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content
    assert '__ract_name__ = "RACT"' in content


# RACT 0.1.0 - Initial Public Release
