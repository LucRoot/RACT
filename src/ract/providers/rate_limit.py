"""Client-side token-bucket rate limiter for provider adapters.

Prevents 429 responses upstream instead of reacting to them.
:class:`TokenBucket` is a plain synchronous limiter — ``acquire`` blocks
until enough tokens have refilled or a timeout expires. The provider
adapter calls ``acquire(1)`` before each outbound request; the retry
policy still handles genuine 429s the server sends despite the client
budget.

Kept deliberately dependency-free (stdlib ``time`` + ``threading``) so
it can sit under every provider without dragging in async plumbing.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from ract.core.module_identity import _module_knot, register_module_knot


class RateLimitTimeout(TimeoutError):
    """Raised when :meth:`TokenBucket.acquire` cannot get tokens in time."""


@dataclass
class TokenBucket:
    """Classic token bucket: ``capacity`` tokens, refilling at ``refill_rate_per_sec``.

    A fresh bucket starts full (``capacity`` tokens available). ``try_acquire``
    is non-blocking and returns whether the tokens were available. ``acquire``
    blocks with a short sleep loop until tokens are available or the timeout
    expires (in which case ``RateLimitTimeout`` fires).
    """

    capacity: int
    refill_rate_per_sec: float
    _tokens: float = field(default=0.0, init=False, repr=False)
    _last_refill: float = field(default=0.0, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError("capacity must be positive")
        if self.refill_rate_per_sec <= 0.0:
            raise ValueError("refill_rate_per_sec must be positive")
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()

    def _refill_locked(self) -> None:
        """Add elapsed-time worth of tokens, capped at ``capacity``.

        Must be called with ``self._lock`` held.
        """
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed <= 0.0:
            return
        self._tokens = min(
            float(self.capacity),
            self._tokens + elapsed * self.refill_rate_per_sec,
        )
        self._last_refill = now

    def available_tokens(self) -> float:
        """Return the currently available token count (after refill)."""
        with self._lock:
            self._refill_locked()
            return self._tokens

    def try_acquire(self, tokens: int = 1) -> bool:
        """Attempt to take ``tokens`` immediately; return whether it succeeded."""
        if tokens <= 0:
            raise ValueError("tokens must be positive")
        with self._lock:
            self._refill_locked()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def acquire(self, tokens: int = 1, timeout: float = 30.0) -> None:
        """Block until ``tokens`` are available or raise :class:`RateLimitTimeout`.

        ``timeout`` is measured on the wall clock (``time.monotonic``).
        Sleep granularity is capped at 50 ms so a wake-up cannot land
        far past the deadline.
        """
        if tokens <= 0:
            raise ValueError("tokens must be positive")
        if tokens > self.capacity:
            raise ValueError(
                f"requested {tokens} tokens exceeds capacity {self.capacity}"
            )
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._lock:
                self._refill_locked()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                # Seconds needed for refill to cover the deficit.
                wait_needed = deficit / self.refill_rate_per_sec
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise RateLimitTimeout(
                    f"could not acquire {tokens} tokens within {timeout}s"
                )
            time.sleep(min(wait_needed, remaining, 0.05))


__all__ = ["RateLimitTimeout", "TokenBucket"]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.4.1
