from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    """Simple token bucket rate limiter.

    Allows bursts up to ``capacity`` and refills at ``refill_rate`` tokens per
    second. All timing uses ``time.monotonic`` so the bucket is not affected by
    system clock changes.
    """

    capacity: float
    refill_rate: float
    _tokens: float = 0.0
    _last_update: float = 0.0

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)
        self._last_update = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        delta = now - self._last_update
        self._tokens = min(self.capacity, self._tokens + delta * self.refill_rate)
        self._last_update = now

    def get_token(self, tokens: float = 1.0) -> bool:
        """Try to consume ``tokens`` tokens. Return True if allowed."""
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def tokens(self) -> float:
        """Return the current number of available tokens."""
        self._refill()
        return self._tokens
