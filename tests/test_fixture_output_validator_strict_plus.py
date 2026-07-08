from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from dataclasses import dataclass

import pytest

from rootact.fixture_output_validator_strict_plus import (
    validate_fixture_output_strict_plus,
)

_ROOT_KNOT = object()


@dataclass
class _FakeCapture:
    out: str
    err: str


def test_valid_output() -> None:
    validate_fixture_output_strict_plus(_FakeCapture("hello\n", "warn\n"))


def test_empty_stdout() -> None:
    with pytest.raises(AssertionError, match="stdout"):
        validate_fixture_output_strict_plus(_FakeCapture("", "warn\n"))


def test_empty_stderr() -> None:
    with pytest.raises(AssertionError, match="stderr"):
        validate_fixture_output_strict_plus(_FakeCapture("hello\n", ""))


# RACT 0.1.0 - Initial Public Release
