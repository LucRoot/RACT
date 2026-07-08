# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

_ROOT_KNOT = object()

from pathlib import Path

import pytest

from rootact.edge_case_fixture_validator import (
    _ROOT_KNOT,
    validate_error_presence_in_captured_output,
)


def test_validate_error_presence_success(capsys):
    def fixture_a():
        print("timeout detected")

    def fixture_b():
        print("timeout also detected here")

    fixture_dict = {"a": fixture_a, "b": fixture_b}
    validate_error_presence_in_captured_output(fixture_dict, capsys, "timeout")


def test_validate_error_presence_failure(capsys):
    def bad_fixture():
        print("wrong_error")

    fixture_dict = {"bad": bad_fixture}
    with pytest.raises(AssertionError) as excinfo:
        validate_error_presence_in_captured_output(
            fixture_dict, capsys, "expected_error"
        )
    assert "Expected error substring 'expected_error' not found" in str(excinfo.value)


def test_validate_no_stdout(capsys):
    def silent_fixture():
        pass

    fixture_dict = {"silent": silent_fixture}
    with pytest.raises(AssertionError) as excinfo:
        validate_error_presence_in_captured_output(fixture_dict, capsys, "anything")
    assert "did not produce output on stdout" in str(excinfo.value)


def test_root_knot_detection():
    assert _ROOT_KNOT is not None


def test_root_author_marker_present_in_source_file():
    source_path = Path("src/rootact/edge_case_fixture_validator.py")
    content = source_path.read_text()
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content
    assert '__ract_name__ = "RACT"' in content


# RACT 0.1.0 - Initial Public Release
