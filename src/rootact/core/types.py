"""Core cryptographic and identity types for RootAct provenance."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Generic, NewType, TypeVar

PlanId = NewType("PlanId", bytes)  # 16 bytes, UUID
StepId = NewType("StepId", bytes)  # 16 bytes, UUID
AssumptionId = NewType("AssumptionId", bytes)  # 16 bytes, UUID
Digest = NewType("Digest", bytes)  # 32 bytes, SHA256

T = TypeVar("T")
E = TypeVar("E")

_UNSET: Any = object()


@dataclass(frozen=True)
class Result(Generic[T, E]):
    """A tiny Either type for explicit error handling."""

    _value: object = field(default=_UNSET)
    _error: E | None = None

    def is_ok(self) -> bool:
        """Return True when the result carries a value, not an error."""
        return self._error is None

    def unwrap(self) -> T:
        """Return the value or raise if this result is an error."""
        if self._error is not None:
            raise ValueError(f"Result is an error: {self._error}")
        if self._value is _UNSET:
            raise ValueError("Result is ok but no value was supplied")
        return self._value  # type: ignore[return-value]

    def unwrap_err(self) -> E:
        """Return the error or raise if this result is ok."""
        if self._error is None:
            raise ValueError("Result is ok, no error to unwrap")
        return self._error

    @classmethod
    def ok(cls, value: T) -> Result[T, E]:
        """Construct an ok result."""
        return cls(_value=value, _error=None)

    @classmethod
    def err(cls, error: E) -> Result[T, E]:
        """Construct an error result."""
        return cls(_value=_UNSET, _error=error)


def make_plan_id() -> PlanId:
    """Return a fresh 16-byte UUID plan identifier."""
    return PlanId(uuid.uuid4().bytes)


def make_step_id() -> StepId:
    """Return a fresh 16-byte UUID step identifier."""
    return StepId(uuid.uuid4().bytes)


def make_assumption_id() -> AssumptionId:
    """Return a fresh 16-byte UUID assumption identifier."""
    return AssumptionId(uuid.uuid4().bytes)


def digest_bytes(data: bytes) -> Digest:
    """Return the SHA256 digest of ``data``."""
    return Digest(sha256(data).digest())


# RACT 0.2.0
