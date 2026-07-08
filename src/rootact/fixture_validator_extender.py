from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import re
from types import SimpleNamespace
from typing import Callable


class _NullCapture:
    """Stand-in capture object when capsys is not provided."""

    def readouterr(self):
        return SimpleNamespace(out="", err="")


def extend_fixture_validation(
    fixture_dict: dict[str, Callable[[], None]],
    capsys,
    expected_error_substring: str,
) -> None:
    """
    Validate and execute pytest fixtures that assert error substrings in captured output.

    This function iterates over ``fixture_dict`` ensuring each key matches the pattern
    ``^test_[a-z][a-z0-9_*]$``, each value is callable, executes the fixture with
    ``capsys`` available, and asserts that ``expected_error_substring`` appears in either
    stdout or stderr.  If any check fails, a descriptive exception is raised.

    Parameters
    ----------
    fixture_dict: dict[str, Callable[[], None]]
        Mapping of fixture names to zero‑argument callables that perform assertions using
        ``capsys``.
    capsys:
        The pytest fixture providing captured output streams.
    expected_error_substring: str
        Substring that must be present in the captured output for a successful assertion.

    Raises
    ------
    ValueError
        If a fixture name does not match the required pattern or if any value is not callable.
    AssertionError
        If the expected substring is not found in the captured output of a fixture.
    """
    for idx, (name, fixture) in enumerate(fixture_dict.items()):
        # Validate fixture name pattern
        if not re.fullmatch(r"test_[a-z][a-z0-9_]*", name):
            raise ValueError(
                f"Fixture name at index {idx} does not match pattern '^test_[a-z][a-z0-9_]*$': '{name}'"
            )
        # Validate callable
        if not callable(fixture):
            raise ValueError(
                f"Value for fixture '{name}' at index {idx} is not callable"
            )
        # Execute fixture with capsys in scope
        fixture()  # This may use capsys internally
        capture = capsys if capsys is not None else _NullCapture()
        captured = capture.readouterr()
        # Assert expected substring presence
        if (
            expected_error_substring not in captured.out
            and expected_error_substring not in captured.err
        ):
            raise AssertionError(
                f"Expected '{expected_error_substring}' not found in output of fixture '{name}'. Captured: out={captured.out!r}, err={captured.err!r}"
            )
