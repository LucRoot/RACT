from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import builtins
import keyword
import re
import uuid
from typing import Any, Dict, List


def validate_and_normalize_fixtures_extended(
    fixtures: List[Dict[str, Any]], user_story: str
) -> List[Dict[str, Any]]:
    """
    Validate and normalize pytest fixture names with extended constraints.

    This function ensures that each fixture's ``pytest_fixture`` value:
      - Starts with 'test_' and matches the pattern 'test_[a-z_][a-z0-9_]*'
      - Contains no uppercase letters or spaces
      - Is unique across the list before normalization
      - Does not collide with built-in Python identifiers or keywords
    After validation, each fixture name is made globally unique by appending an 8-character UUID suffix.
    A new list of fixtures with normalized and deduplicated names is returned.
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

        # Validate pattern after lowercasing (pattern is case-sensitive but we enforce lowercase)
        normalized_raw = raw_name.lower()
        if not re.fullmatch(r"test_[a-z_][a-z0-9_]*", normalized_raw):
            raise ValueError(
                f"Fixture name at index {idx} does not match pattern 'test_[a-z_][a-z0-9_]*' after lowercasing: '{raw_name}'"
            )

        # Check for duplicates before normalization
        if raw_name in seen_names:
            raise ValueError(f"Duplicate fixture name found: '{raw_name}'")
        seen_names.add(raw_name)

        # Normalize to lowercase (already validated pattern ensures safety)
        normalized_name = normalized_raw

        # Check collision with built-in identifiers or keywords
        suffix_name = normalized_name[len("test_") :]
        if suffix_name in dir(builtins):
            raise ValueError(
                f"Normalized fixture name collides with built-in identifier: '{normalized_name}'"
            )
        if keyword.iskeyword(suffix_name):
            raise ValueError(
                f"Normalized fixture name is a Python keyword: '{normalized_name}'"
            )

        # Ensure uniqueness by appending UUID suffix without mutating the input
        suffix = uuid.uuid4().hex[:8]
        unique_name = f"{normalized_name}_{suffix}"
        normalized_fixture = dict(fixture)
        normalized_fixture["pytest_fixture"] = unique_name
        normalized_fixtures.append(normalized_fixture)

    return normalized_fixtures


# RACT 0.1.0 - Initial Public Release
