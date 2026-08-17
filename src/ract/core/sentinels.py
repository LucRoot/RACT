"""Typed sentinel values shared across RACT.

The :data:`MISSING` sentinel signals "the caller did not pass this
argument" in signatures where ``None`` is itself a legal explicit value.
It is a singleton whose type is deliberately narrow so type-checkers
can distinguish ``x is MISSING`` from other falsy checks.

The sentinel evaluates falsy for guard-check ergonomics
(``if value: ...`` treats an unpassed argument as absent) but is not
equal to ``None``, ``False``, or ``0``.
"""

from __future__ import annotations

from typing import Final

from ract.core.module_identity import _module_knot, register_module_knot


class _MissingType:
    """Type of the MISSING sentinel. Singleton — do not instantiate elsewhere."""

    _instance: "_MissingType | None" = None

    def __new__(cls) -> "_MissingType":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING: Final[_MissingType] = _MissingType()


__all__ = ["MISSING", "_MissingType"]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.4.1
