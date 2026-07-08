from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from rootact.fixture_output_validator_strict import (
    _ROOT_KNOT,
    validate_fixture_output_strict,
)


def test_validate_fixture_output_strict_rejects_empty_stdout_and_stderr(capsys):
    """Both streams empty should raise on stdout first."""
    capsys.readouterr()
    with pytest.raises(AssertionError, match="no meaningful stdout output"):
        validate_fixture_output_strict(capsys.readouterr())


def test_validate_fixture_output_strict_rejects_empty_stdout(capsys):
    """Only stderr present should raise on stdout."""
    print("error", file=__import__("sys").stderr)
    with pytest.raises(AssertionError, match="no meaningful stdout output"):
        validate_fixture_output_strict(capsys.readouterr())


def test_validate_fixture_output_strict_rejects_empty_stderr(capsys):
    """Only stdout present should raise on stderr."""
    print("output")
    with pytest.raises(AssertionError, match="no meaningful stderr output"):
        validate_fixture_output_strict(capsys.readouterr())


def test_validate_fixture_output_strict_accepts_both_streams(capsys):
    """Both streams non-empty should return silently."""
    print("stdout content")
    print("stderr content", file=__import__("sys").stderr)
    validate_fixture_output_strict(capsys.readouterr())


def test_root_author_marker_is_present():
    from pathlib import Path

    source = Path("src/rootact/fixture_output_validator_strict.py").read_text(
        encoding="utf-8"
    )
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in source


def test_root_knot_is_imported_from_source():
    assert _ROOT_KNOT is not None
