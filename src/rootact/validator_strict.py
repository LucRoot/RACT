from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import builtins
import keyword
import re
from typing import Dict, Any

_fixture_registry: set[str] = set()

# Canonical Python identifiers that a fixture suffix must not shadow.
_RESERVED_NAMES: set[str] = set(dir(builtins)) | set(keyword.kwlist)


def _reset_fixture_registry() -> None:
    """Clear the module-level fixture registry. Intended for tests only."""
    _fixture_registry.clear()


def validate_fixture(fixture: Dict[str, Any]) -> str:
    """
    Validate a fixture dictionary and return its normalized name.

    The function checks that the input is a dictionary containing a ``pytest_fixture``
    key with a string value matching the pattern ``test_[a-z_][a-z0-9_]*``.  Whitespace
    is stripped, the name is lower‑cased, and it is verified not to collide with any
    built‑in Python identifier or keyword.  If all checks pass, the normalized name is
    returned.
    """
    if not isinstance(fixture, dict):
        raise ValueError("'fixture' must be a dictionary")
    if "pytest_fixture" not in fixture:
        raise ValueError("'pytest_fixture' key is missing from fixture")
    raw_name: str = fixture["pytest_fixture"]
    if not isinstance(raw_name, str):
        raise ValueError("'pytest_fixture' value must be a string")

    normalized = raw_name.strip().lower()
    if not re.fullmatch(r"test_[a-z_][a-z0-9_]*", normalized):
        raise ValueError(
            f"Fixture name '{raw_name.strip()}' does not match pattern 'test_[a-z_][a-z0-9_]*'"
        )

    suffix = normalized[len("test_") :]
    if suffix in _RESERVED_NAMES:
        raise ValueError(
            f"Normalized fixture name collides with built-in identifier: '{normalized}'"
        )

    return normalized


def assert_fixture_uniqueness(fixture_name: str) -> None:
    """
    Ensure that ``fixture_name`` has not been registered in the current session.

    If the name already exists, a ``ValueError`` is raised.  Otherwise the name is added
    to the module‑level registry and the function returns ``None``.
    """
    if not isinstance(fixture_name, str):
        raise ValueError("'fixture_name' must be a string")
    normalized_name = fixture_name.lower()
    if normalized_name in _fixture_registry:
        raise ValueError(f"Fixture name '{fixture_name}' has already been registered")
    _fixture_registry.add(normalized_name)
