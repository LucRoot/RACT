# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Documentation mode for RootAct.

When enabled, RootAct records code changes so that documentation can be updated
as a deliberate, trackable part of the build loop.
"""

import copy


class DocumentationMode:
    """Manages documentation generation and update workflows in Documentation Mode."""

    def __init__(self) -> None:
        self._enabled = False
        self._changes: list[dict] = []

    def enable(self) -> None:
        """Enable Documentation Mode."""
        self._enabled = True

    def disable(self) -> None:
        """Disable Documentation Mode."""
        self._enabled = False

    def is_enabled(self) -> bool:
        """Return whether Documentation Mode is enabled."""
        return self._enabled

    def record_change(self, path: str, description: str) -> None:
        """Record a code change for documentation update."""
        if not self._enabled:
            raise RuntimeError(
                "Cannot record changes when Documentation Mode is disabled."
            )
        self._changes.append(
            {
                "path": path,
                "description": description,
                "id": id(self._changes[-1]) if self._changes else 0,
            }
        )

    def list_recorded_changes(self) -> list[dict]:
        """Return a deep copy of recorded changes for documentation update."""
        return copy.deepcopy(self._changes)

    def apply_to_intent(self, intent: str) -> str:
        """Return a documentation-focused version of the user's intent."""
        if not self._enabled:
            return intent
        return (
            "DOCUMENTATION MODE:\n"
            "Before changing implementation, update or create the following "
            "documentation so it stays accurate and complete. "
            "Prefer README, ARCHITECTURE, AUDIT, and inline docstrings.\n\n"
            f"Original intent: {intent}"
        )


# RACT 0.1.0 - Initial Public Release
