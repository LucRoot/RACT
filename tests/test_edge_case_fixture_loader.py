from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from rootact.edge_case_fixture_loader import load_and_validate_fixtures


def test_load_and_validate_fixtures_success(capsys):
    def fixture_a() -> None:
        print("error_type: network timeout")

    def fixture_b() -> None:
        import sys

        sys.stderr.write("error_type: duplicate charge")

    fixture_dict = {"a": fixture_a, "b": fixture_b}
    result = load_and_validate_fixtures(fixture_dict, capsys)
    assert isinstance(result, dict)
    assert "a" in result
    assert "b" in result


def test_load_and_validate_fixtures_missing_stdout(capsys):
    def bad_fixture() -> None:
        pass  # No output at all

    fixture_dict = {"bad": bad_fixture}
    with pytest.raises(AssertionError, match="did not produce output"):
        load_and_validate_fixtures(fixture_dict, capsys)


def test_load_and_validate_fixtures_missing_error_substring(capsys):
    def fixture_no_error() -> None:
        print("some output without the expected key")

    fixture_dict = {"no_error": fixture_no_error}
    with pytest.raises(AssertionError, match="expected error substring"):
        load_and_validate_fixtures(
            fixture_dict, capsys, expected_error="expected_error"
        )


# RACT 0.1.0 - Initial Public Release
