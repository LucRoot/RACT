# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Ordered fallback chain for RACT inference endpoints.

Tries a list of endpoints in priority order, records which succeeded, and
returns the first successful result plus metadata.  Keeps the fallback logic
isolated from endpoint-specific adapters so any callable (HTTP, local, mock)
can be wrapped.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class FallbackResult:
    """Result of a fallback-chain attempt."""

    success: bool
    value: Any = None
    error: Optional[str] = None
    endpoint: Optional[str] = None
    attempts: List[Dict[str, Any]] = field(default_factory=list)

    def unwrap(self) -> Any:
        """Return the successful value or raise RuntimeError."""
        if not self.success:
            raise RuntimeError(self.error or "all fallback endpoints failed")
        return self.value


class FallbackChain:
    """Try endpoints in order until one succeeds.

    ``call_fn`` receives the endpoint configuration dict and should return a
    result or raise an exception.  The chain stops at the first successful call
    and records every attempt.
    """

    def __init__(
        self,
        endpoints: List[Dict[str, Any]],
        call_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> None:
        self.endpoints = list(endpoints)
        self.call_fn = call_fn

    def try_endpoints(
        self,
        call_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> FallbackResult:
        """Walk the endpoint list and return the first success.

        Args:
            call_fn: Optional override for the constructor-provided callable.

        Returns:
            FallbackResult with ``success=True`` if any endpoint returned a
            value without raising.
        """
        fn = call_fn or self.call_fn
        if fn is None:
            raise ValueError("call_fn must be provided to try_endpoints")
        attempts: List[Dict[str, Any]] = []
        for idx, endpoint in enumerate(self.endpoints):
            name = endpoint.get("name", endpoint.get("slot_id", f"endpoint_{idx}"))
            try:
                value = fn(endpoint)
                attempts.append(
                    {
                        "endpoint": name,
                        "config": endpoint,
                        "success": True,
                        "index": idx,
                    }
                )
                return FallbackResult(
                    success=True,
                    value=value,
                    endpoint=name,
                    attempts=attempts,
                )
            except Exception as exc:  # noqa: BLE001 - every endpoint gets a chance
                attempts.append(
                    {
                        "endpoint": name,
                        "config": endpoint,
                        "success": False,
                        "error": str(exc),
                        "index": idx,
                    }
                )
        last_error = (
            attempts[-1].get("error") if attempts else "no endpoints configured"
        )
        return FallbackResult(
            success=False,
            error=last_error,
            attempts=attempts,
        )

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        call_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> "FallbackChain":
        """Build a chain from a config dict with an ``endpoints`` list."""
        endpoints = config.get("endpoints", [])
        if not isinstance(endpoints, list):
            raise ValueError("config.endpoints must be a list")
        return cls(endpoints, call_fn=call_fn)
