from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import re
from typing import Callable

from rootact.manager import Plan, Step

_ROOT_KNOT = object()

_fixture_pattern = re.compile(r"^test_[a-z][a-z0-9_]*$")


def extend_fixture_validation(
    fixture_dict: dict[str, Callable[[], None]],
    capsys,
    expected_error_substring: str,
) -> None:
    """
    Validate that each fixture name matches the pattern '^test_[a-z][a-z0-9_*]$',
    ensure each value is callable, execute the fixture with ``capsys`` in scope,
    and assert that ``expected_error_substring`` appears in either stdout or stderr.

    Parameters
    ----------
    fixture_dict: dict[str, Callable[[], None]]
        Mapping of fixture names to callables that perform assertions.
    capsys:
        The pytest capture fixture used to obtain captured output.
    expected_error_substring: str
        Substring that must be present in either ``captured.out`` or ``captured.err``.

    Raises
    ------
    ValueError
        If a fixture name does not match the pattern or if any value is not callable.
    AssertionError
        If the expected error substring is absent from both captured output streams.
    """
    for idx, (name, value) in enumerate(fixture_dict.items()):
        if not _fixture_pattern.fullmatch(name):
            raise ValueError(
                f"Fixture name at index {idx} does not match pattern '^test_[a-z][a-z0-9_*]$': '{name}'"
            )
        if not callable(value):
            raise ValueError(f"Value for fixture '{name}' is not callable.")
        value()  # Execute the fixture with capsys in scope
        captured = capsys.readouterr()
        if (
            expected_error_substring not in captured.out
            and expected_error_substring not in captured.err
        ):
            raise AssertionError(
                f"Expected '{expected_error_substring}' not found in captured output (out={captured.out!r}, err={captured.err!r})"
            )


_plan = Plan(
    assumption="RootAct must validate fixture names, callability, and error substring presence",
    confidence=0.96,
    steps=[
        Step(
            action="extend_fixture_validation",
            provider_hint="internal",
            expected_artifact="None",
        )
    ],
)
# RACT 0.1.0 - Initial Public Release
