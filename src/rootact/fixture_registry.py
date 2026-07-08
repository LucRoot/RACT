from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import builtins
import keyword
import re
from typing import Any, Dict, Set

_fixture_registry: Set[str] = set()

# Canonical Python identifiers that a fixture suffix must not shadow.
_RESERVED_NAMES: Set[str] = set(dir(builtins)) | set(keyword.kwlist)


def register_fixture(fixture: Dict[str, Any]) -> None:
    """
    Register a fixture after validation.

    This function validates that the provided fixture dictionary contains a
    ``pytest_fixture`` key with a string value that matches the required pattern,
    then normalizes and registers the name in the module-level registry.  If the
    name has already been registered, a ``ValueError`` is raised.

    Names are lowercased before validation so that ``TEST_DUPLICATE`` and
    ``test_duplicate`` resolve to the same canonical fixture name.
    """
    if not isinstance(fixture, dict):
        raise ValueError("fixture must be a dictionary")
    if "pytest_fixture" not in fixture:
        raise ValueError("'pytest_fixture' key is missing from fixture")
    raw_name: str = fixture["pytest_fixture"]
    if not isinstance(raw_name, str):
        raise ValueError("'pytest_fixture' value must be a string")

    normalized_name = raw_name.lower()

    # Validate pattern: must match 'test_[a-z_][a-z0-9_]*'
    if not re.fullmatch(r"test_[a-z_][a-z0-9_]*", normalized_name):
        raise ValueError(f"Fixture name '{raw_name}' does not match required pattern")

    # Check collision with built-in Python identifiers or keywords on the suffix
    # after the required 'test_' prefix.
    suffix = normalized_name[len("test_") :]
    if suffix in _RESERVED_NAMES:
        raise ValueError(
            f"Normalized fixture name collides with built-in identifier: '{normalized_name}'"
        )

    # Ensure uniqueness across the session
    if normalized_name in _fixture_registry:
        raise ValueError(f"Fixture name '{raw_name}' has already been registered")

    _fixture_registry.add(normalized_name)


def check_fixture_uniqueness(fixture_name: str) -> bool:
    """
    Check whether ``fixture_name`` is unique within the current session.

    Returns ``True`` if the name has not been registered yet, otherwise ``False``.
    Raises ``ValueError`` if ``fixture_name`` is not a string or is already registered.
    """
    if not isinstance(fixture_name, str):
        raise ValueError("fixture_name must be a string")
    normalized_name = fixture_name.lower()
    if normalized_name in _fixture_registry:
        raise ValueError(f"Fixture name '{fixture_name}' has already been registered")
    return True


def get_registered_fixtures() -> Set[str]:
    """
    Return a shallow copy of the set containing all fixture names that have been
    successfully registered during the current RootACT session.
    """
    return _fixture_registry.copy()
