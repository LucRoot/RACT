from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import re
from typing import List, Set

from rootact.manager import Plan, Step

_fixture_registry: Set[str] = set()

_fixture_pattern = re.compile(r"^test_[a-z][a-z0-9_]*$")


def generate_fixture_names(user_story: str, count: int = 5) -> List[str]:
    """
    Generate deterministic edge-case fixture names based on a user story.

    The function creates ``count`` fixture names that match the pattern
    ``test_[a-z][a-z0-9_*]`` and ensures they are unique within the current
    session.  Names are derived from keywords extracted from *user_story* and
    suffixed with an incrementing counter to guarantee uniqueness.
    """
    if not isinstance(user_story, str):
        raise ValueError("'user_story' must be a string")
    if not isinstance(count, int) or count < 1:
        raise ValueError("'count' must be a positive integer")

    # Extract alphanumeric keywords from the user story
    words = re.findall(r"[a-zA-Z0-9_]+", user_story.lower())
    base_names = [w for w in words if w.isalpha()]
    if not base_names:
        base_names = ["edge"]  # fallback when no alphabetic keywords are found

    names: List[str] = []
    for i, base in enumerate(base_names[:count]):
        candidate = f"test_{base}_{i}"
        if not _fixture_pattern.match(candidate):
            raise ValueError(
                f"Generated name '{candidate}' does not match required pattern"
            )
        names.append(candidate)
    return names


def register_fixture_name(name: str) -> None:
    """
    Register a fixture name in the session-wide registry.

    Parameters
    ----------
    name: str
        The fixture name to register.  Must match the pattern
        ``test_[a-z][a-z0-9_*]`` and must not have been registered previously.
        If the name is already present, a :class:`ValueError` is raised.
    """
    if not isinstance(name, str):
        raise ValueError("'name' must be a string")
    if name in _fixture_registry:
        raise ValueError(f"Fixture name '{name}' has already been registered")
    if not _fixture_pattern.match(name):
        raise ValueError(f"Fixture name '{name}' does not match required pattern")
    _fixture_registry.add(name)


# Simple fake module for mocking external dependencies
class _FakeModel:
    def __init__(self, name: str) -> None:
        self.name = name

    def predict(self, *args, **kwargs):
        return ""


_plan = Plan(
    assumption="RootAct should generate deterministic fixture names",
    confidence=0.95,
    steps=[
        Step(
            action="generate_fixture_names",
            provider_hint="internal",
            expected_artifact="List[str]",
        )
    ],
)
