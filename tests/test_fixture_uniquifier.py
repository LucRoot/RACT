from __future__ import annotations

_ROOT_KNOT = object()

import pytest
from pathlib import Path

from rootact.fixture_uniquifier import ensure_unique_fixtures


def test_ensure_unique_fixtures_basic_transform():
    fixtures = [
        {"pytest_fixture": "test_user", "param": 1},
        {"pytest_fixture": "test_order", "param": 2},
    ]
    result = ensure_unique_fixtures(fixtures)
    assert len(result) == 2
    for fixture in result:
        assert "pytest_fixture" in fixture
        assert (
            fixture["pytest_fixture"].endswith("_XXXXXXXX")
            or "_" in fixture["pytest_fixture"]
        )
        # Ensure other keys are preserved
        original = next(
            f
            for f in fixtures
            if fixture["pytest_fixture"].startswith(f["pytest_fixture"] + "_")
        )
        assert fixture["param"] == original["param"]


def test_ensure_unique_fixtures_detects_duplicates():
    fixtures = [
        {"pytest_fixture": "duplicate", "value": 1},
        {"pytest_fixture": "duplicate", "value": 2},
    ]
    with pytest.raises(ValueError, match="Duplicate fixture name detected"):
        ensure_unique_fixtures(fixtures)


def test_ensure_unique_fixtures_invalid_input_type():
    fixtures = [123]
    with pytest.raises(ValueError, match="Each fixture must be a dictionary"):
        ensure_unique_fixtures(fixtures)


def test_ensure_unique_fixtures_missing_pytest_fixture_key():
    fixtures = [{}]
    with pytest.raises(
        ValueError, match="Each fixture must contain a 'pytest_fixture' key"
    ):
        ensure_unique_fixtures(fixtures)


def test_ensure_unique_fixtures_non_string_fixture_name():
    fixtures = [{"pytest_fixture": 123}]
    with pytest.raises(ValueError, match="'pytest_fixture' value must be a string"):
        ensure_unique_fixtures(fixtures)


def test_root_author_marker_present_in_source_file():
    source_path = Path("src/rootact/fixture_uniquifier.py")
    content = source_path.read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content
    assert '__ract_name__ = "RACT"' in content
