from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import re
from typing import Any, Dict, List


def normalize_pytest_fixture_names(
    fixtures: List[Dict[str, Any]], user_story: str
) -> List[Dict[str, Any]]:
    """
    Normalize pytest fixture names to adhere to strict naming conventions.

    This function validates that each fixture's 'pytest_fixture' value:
      - Starts with 'test_' and follows the pattern 'test_[a-z_][a-z0-9_]*'
      - Contains only lowercase letters, digits, and underscores after 'test_'
      - Is unique across the list
      - Does not conflict with built-in names (no uppercase or spaces)

    If any validation fails, a ValueError is raised with a descriptive message.
    Otherwise, a new list of fixtures is returned with normalized and deduplicated
    fixture names, preserving all other keys and values.
    """
    if not isinstance(fixtures, list):
        raise ValueError("fixtures must be a list of dictionaries")

    seen_names = set()
    normalized_fixtures: List[Dict[str, Any]] = []

    for idx, fixture in enumerate(fixtures):
        if not isinstance(fixture, dict):
            raise ValueError(f"Fixture at index {idx} is not a dictionary")

        if "pytest_fixture" not in fixture:
            raise ValueError(f"Fixture at index {idx} is missing 'pytest_fixture' key")

        raw_name = fixture["pytest_fixture"]
        if not isinstance(raw_name, str):
            raise ValueError(f"'pytest_fixture' value at index {idx} must be a string")

        # Check for uppercase letters or spaces
        if re.search(r"[A-Z\s]", raw_name):
            raise ValueError(
                f"Fixture name at index {idx} contains uppercase letters or spaces: '{raw_name}'"
            )

        # Validate pattern: must start with 'test_' and then conform to a valid identifier.
        if not raw_name.startswith("test_"):
            raise ValueError(
                f"Fixture name at index {idx} does not start with 'test_': '{raw_name}'"
            )
        suffix = raw_name[len("test_") :]
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", suffix):
            raise ValueError(
                f"Fixture name at index {idx} does not conform to valid Python identifier pattern: '{raw_name}'"
            )

        # Check for duplicates
        if raw_name in seen_names:
            raise ValueError(f"Duplicate fixture name found: '{raw_name}'")
        seen_names.add(raw_name)

        normalized_fixtures.append(fixture)

    return normalized_fixtures
