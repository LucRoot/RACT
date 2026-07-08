from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import re
from typing import Any, Dict, List


def validate_fixtures_strict(fixtures: List[Dict[str, Any]], user_story: str) -> None:
    """
    Validate a list of test fixtures for structural and naming criteria.

    This function raises ValueError with a descriptive message if any fixture fails
    the following checks:
      - Must be a dictionary
      - Must contain a 'pytest_fixture' key that is a string
      - The fixture name must start with 'test_' and conform to valid Python identifier rules

    Parameters
    ----------
    fixtures: List[Dict[str, Any]]
        The list of test fixtures to validate.
    user_story: str
        The original user story (unused in validation but required by signature).

    Raises
    ------
    ValueError
        If any fixture fails the structural or naming criteria.
    """
    if not isinstance(fixtures, list):
        raise ValueError("fixtures must be a list of dictionaries")

    for idx, fixture in enumerate(fixtures):
        if not isinstance(fixture, dict):
            raise ValueError(f"Fixture at index {idx} is not a dictionary")

        if "pytest_fixture" not in fixture:
            raise ValueError(f"Fixture at index {idx} is missing 'pytest_fixture' key")

        fixture_name = fixture["pytest_fixture"]
        if not isinstance(fixture_name, str):
            raise ValueError(f"'pytest_fixture' value at index {idx} must be a string")

        if not fixture_name.startswith("test_"):
            raise ValueError(f"Fixture name at index {idx} does not start with 'test_'")

        # Check for valid Python identifier (no spaces, starts with letter/underscore, alphanumeric + underscore)
        if not re.fullmatch(r"test_[a-zA-Z_][a-zA-Z0-9_]*", fixture_name):
            raise ValueError(
                f"Fixture name at index {idx} does not conform to valid Python identifier pattern: '{fixture_name}'"
            )

    # All checks passed
    return None


# RACT 0.1.0 - Initial Public Release
