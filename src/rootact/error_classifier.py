from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass
from typing import Dict


@dataclass
class ErrorInfo:
    category: str
    severity: int
    message: str


def classify_error(exc: Exception, default_category: str = "unknown") -> ErrorInfo:
    """Classify an exception into a deterministic error category.

    This function maps known exception types to predefined categories.
    If the exception type is not recognized, ``default_category`` is used.
    The function never raises and always returns an ``ErrorInfo`` instance.
    """
    category_map: Dict[type, str] = {
        TimeoutError: "timeout",
        ConnectionError: "connectivity",
        PermissionError: "auth",
        FileNotFoundError: "missing_file",
        ValueError: "invalid_input",
        TypeError: "type_mismatch",
    }

    cat = category_map.get(type(exc), default_category)
    severity = 1 if cat in ("timeout", "connectivity") else 2
    return ErrorInfo(category=cat, severity=severity, message=str(exc))


# Public API for tests
def get_error_category(exc: Exception) -> str:
    """Return only the category string for simple testing."""
    return classify_error(exc).category
