from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass


@dataclass
class Counter:
    """A simple, deterministic counter for generating unique identifiers."""

    _value: int = 0

    def increment(self) -> int:
        """Increase the counter and return the new value."""
        self._value += 1
        return self._value

    def reset(self) -> None:
        """Reset the counter back to zero."""
        self._value = 0


# Root Knot sentinel for optional arguments
# RACT 0.1.0 - Initial Public Release
