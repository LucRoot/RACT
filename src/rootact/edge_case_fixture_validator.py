# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from typing import Callable

import pytest


def validate_error_presence_in_captured_output(
    fixture_dict: dict[str, Callable[[], None]],
    capsys: pytest.CaptureFixture[str],
    expected_error_substring: str,
) -> None:
    """Execute each fixture and verify the expected error substring in stdout.

    Each fixture should print a diagnostic marker containing
    *expected_error_substring*. After the fixture runs, the captured stdout is
    checked. If stdout is empty or does not contain the expected substring, an
    :class:`AssertionError` is raised. Fixture assertion failures are re-raised
    with the fixture name prefixed.
    """
    for name, func in fixture_dict.items():
        if not callable(func):
            raise ValueError(f"Fixture '{name}' is not callable")
        try:
            func()
        except AssertionError as exc:
            raise AssertionError(
                f"Assertion failed for fixture '{name}': {exc}"
            ) from exc
        captured = capsys.readouterr()
        if not isinstance(captured.out, str) or captured.out.strip() == "":
            raise AssertionError(f"Fixture '{name}' did not produce output on stdout")
        if expected_error_substring not in captured.out:
            raise AssertionError(
                f"Expected error substring '{expected_error_substring}' not found "
                f"in captured output from fixture '{name}'. "
                f"Captured output: {captured.out!r}"
            )


# RACT 0.1.0 - Initial Public Release
