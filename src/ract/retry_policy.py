from __future__ import annotations


import datetime
import math
import random
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")

# The HTTP-date form of Retry-After (IMF-fixdate, RFC 9110). Other spellings
# are not parsed and fall back to backoff.
_HTTP_DATE_FORMAT = "%a, %d %b %Y %H:%M:%S GMT"

# Wait before the one retry of a connection nothing answered (B-043).
_QUICK_RETRY_DELAY = 0.25

# The longest wait a server's Retry-After may ask for. Longer than this and
# RACT stops the retries instead of sleeping for it (B-055).
MAX_RETRY_AFTER_S = 120.0

# A wait runs in slices this long, so a cancel is seen within a quarter second.
_WAIT_SLICE_S = 0.25


def parse_retry_after(value: object, now: float | None = None) -> float | None:
    """Seconds that a ``Retry-After`` header asks us to wait, or None.

    The header is a count of seconds or an HTTP date. Garbage, negative and
    non-finite values give None, so the caller falls back to its backoff. A
    date already past gives zero.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        seconds = float(text)
    except ValueError:
        seconds = None
    if seconds is not None:
        if not math.isfinite(seconds) or seconds < 0:
            return None
        return seconds
    try:
        when = datetime.datetime.strptime(text, _HTTP_DATE_FORMAT)
    except ValueError:
        return None
    current = time.time() if now is None else now
    return max(0.0, when.replace(tzinfo=datetime.timezone.utc).timestamp() - current)


def wait_interruptibly(
    seconds: float,
    cancelled: Callable[[], bool],
    sleeper: Callable[[float], None] | None = None,
) -> None:
    """Sleep for *seconds*, but stop early once *cancelled* is true (B-055)."""
    sleep = sleeper or time.sleep
    remaining = seconds
    while remaining > 0 and not cancelled():
        step = min(_WAIT_SLICE_S, remaining)
        sleep(step)
        remaining -= step


@dataclass
class RetryConfig:
    """Parameters that control backoff timing.

    Example::

        config = RetryConfig(
            max_retries=3, base_delay=0.1, max_delay=1.0, jitter=False
        )
    """

    max_retries: int
    base_delay: float
    max_delay: float
    jitter: bool
    backoff: float = 2.0
    # Source of the jitter draw, a value in [0, 1). Tests inject a seeded one.
    rand: Callable[[], float] | None = None

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.base_delay < 0:
            raise ValueError("base_delay must be non-negative")
        if self.max_delay < 0:
            raise ValueError("max_delay must be non-negative")
        if self.backoff < 1.0:
            raise ValueError("backoff must be at least 1")


@dataclass
class RetryPolicy:
    """Execute a callable with configurable retry/backoff.

    Example::

        from ract.retry_policy import RetryConfig, RetryPolicy

        config = RetryConfig(max_retries=2, base_delay=0.1, max_delay=1.0, jitter=False)
        policy = RetryPolicy(config=config)
        value, error = policy.execute(
            fn=lambda: "success",
            is_retryable=lambda _exc: True,
        )
        assert value == "success"
        assert error is None
    """

    config: RetryConfig

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.config.max_retries

    def calculate_delay(self, attempt: int) -> float:
        """Backoff before retry *attempt* (1-based).

        With jitter the delay is the exponential value times a factor in
        [0.5, 1.0), so two waits in a row are never the same length.
        """
        if attempt <= 0:
            return 0.0
        delay = min(
            self.config.base_delay * self.config.backoff ** (attempt - 1),
            self.config.max_delay,
        )
        if self.config.jitter:
            draw = random.random if self.config.rand is None else self.config.rand
            delay *= 0.5 + 0.5 * draw()
        return delay

    def wait_before(self, attempt: int, retry_after: float | None) -> float | None:
        """Seconds to wait before retry *attempt*, or None to stop instead.

        A usable ``Retry-After`` replaces the backoff. One above
        MAX_RETRY_AFTER_S stops the retries.
        """
        if retry_after is None:
            return self.calculate_delay(attempt)
        if retry_after > MAX_RETRY_AFTER_S:
            return None
        return retry_after

    def execute(
        self,
        fn: Callable[[], T],
        is_retryable: Callable[[Exception], bool],
        sleep: Callable[[float], None] | None = None,
        on_retry: Callable[[int, int, str, float], None] | None = None,
        *,
        quick: Callable[[Exception], bool] | None = None,
        describe: Callable[[Exception], str] | None = None,
        retry_after: Callable[[Exception], float | None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[T | None, Exception | None]:
        """Run *fn* until it succeeds, retries are exhausted, or failure is final.

        Returns a tuple of (value, error). Exactly one of the two is None on a
        clean success or final failure; both may be None only if *fn* returns
        None on a successful attempt.

        ``on_retry(attempt, max_attempts, reason, wait_s)`` is called before
        each wait, so a session can show the retry instead of going silent
        (UX-04: three retries over 16 to 25 s with nothing on screen).

        An error for which ``quick`` is true (nothing is listening) gets one
        retry after a short wait instead of the full backoff (B-043).
        ``describe`` turns an error into the plain reason shown on a retry
        line; without it the reason is the exception text.

        ``retry_after(exc)`` gives the server's requested wait for an error,
        or None. ``cancelled()`` is checked during every wait, so a cancel
        ends the wait within a quarter second and no new attempt is made.
        """
        sleeper = sleep or time.sleep
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                return fn(), None
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                fast = quick is not None and quick(exc)
                limit = (
                    min(1, self.config.max_retries) if fast else self.config.max_retries
                )
                if attempt >= limit or not is_retryable(exc):
                    break
                if fast:
                    delay = min(self.calculate_delay(attempt + 1), _QUICK_RETRY_DELAY)
                else:
                    asked = retry_after(exc) if retry_after is not None else None
                    planned = self.wait_before(attempt + 1, asked)
                    if planned is None:
                        break
                    delay = planned
                if on_retry is not None:
                    reason = (
                        describe(exc)
                        if describe is not None
                        else " ".join(f"{type(exc).__name__}: {exc}".split())[:120]
                    )
                    on_retry(attempt + 1, limit, reason, delay)
                if cancelled is None:
                    sleeper(delay)
                else:
                    wait_interruptibly(delay, cancelled, sleeper)
                    if cancelled():
                        break

        return None, last_error


# RACT 0.1.1 - Trust and tooling
