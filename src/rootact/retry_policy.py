# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass
class RetryConfig:
    max_retries: int
    base_delay: float
    max_delay: float
    jitter: bool

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.base_delay < 0:
            raise ValueError("base_delay must be non-negative")
        if self.max_delay < 0:
            raise ValueError("max_delay must be non-negative")


@dataclass
class RetryPolicy:
    config: RetryConfig

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.config.max_retries

    def calculate_delay(self, attempt: int) -> float:
        if attempt <= 0:
            return 0.0
        delay = min(
            self.config.base_delay * (2 ** (attempt - 1)), self.config.max_delay
        )
        if self.config.jitter:
            delay *= 0.5 + time.time() % 1.0
        return delay

    def execute(
        self,
        fn: Callable[[], T],
        is_retryable: Callable[[Exception], bool],
        sleep: Callable[[float], None] | None = None,
    ) -> tuple[T | None, Exception | None]:
        """Run *fn* until it succeeds, retries are exhausted, or failure is final.

        Returns a tuple of (value, error). Exactly one of the two is None on a
        clean success or final failure; both may be None only if *fn* returns
        None on a successful attempt.
        """
        sleeper = sleep or time.sleep
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                return fn(), None
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self.config.max_retries or not is_retryable(exc):
                    break
                sleeper(self.calculate_delay(attempt + 1))

        return None, last_error


# RACT 0.1.1 - Trust and tooling
