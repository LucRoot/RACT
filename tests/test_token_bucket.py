"""Tests for the client-side TokenBucket rate limiter."""

from __future__ import annotations

import threading
import time

import pytest

from ract.providers.rate_limit import RateLimitTimeout, TokenBucket


def test_bucket_starts_full() -> None:
    b = TokenBucket(capacity=5, refill_rate_per_sec=1.0)
    assert b.available_tokens() == pytest.approx(5.0, abs=0.01)


def test_bucket_refills_over_time() -> None:
    b = TokenBucket(capacity=5, refill_rate_per_sec=10.0)
    for _ in range(5):
        assert b.try_acquire(1) is True
    assert b.try_acquire(1) is False
    time.sleep(0.2)
    # 0.2s * 10 tok/s = ~2 tokens refilled
    assert b.available_tokens() >= 1.5


def test_bucket_try_acquire_fails_when_empty() -> None:
    b = TokenBucket(capacity=2, refill_rate_per_sec=0.001)
    assert b.try_acquire(1) is True
    assert b.try_acquire(1) is True
    assert b.try_acquire(1) is False


def test_bucket_acquire_blocks_and_returns() -> None:
    b = TokenBucket(capacity=1, refill_rate_per_sec=20.0)
    assert b.try_acquire(1) is True  # drain

    done = threading.Event()
    started = time.monotonic()

    def _worker() -> None:
        b.acquire(1, timeout=2.0)
        done.set()

    t = threading.Thread(target=_worker)
    t.start()
    t.join(timeout=2.0)
    elapsed = time.monotonic() - started
    assert done.is_set(), "acquire did not return within budget"
    # A refill of 1 tok at 20 tok/s = 0.05s; allow generous scheduling slack.
    assert 0.02 <= elapsed <= 1.0


def test_bucket_acquire_timeout_raises() -> None:
    b = TokenBucket(capacity=1, refill_rate_per_sec=0.01)
    assert b.try_acquire(1) is True  # drain
    with pytest.raises(RateLimitTimeout):
        b.acquire(1, timeout=0.1)


def test_bucket_rejects_nonpositive_capacity() -> None:
    with pytest.raises(ValueError):
        TokenBucket(capacity=0, refill_rate_per_sec=1.0)
    with pytest.raises(ValueError):
        TokenBucket(capacity=1, refill_rate_per_sec=0.0)


def test_bucket_rejects_acquire_larger_than_capacity() -> None:
    b = TokenBucket(capacity=2, refill_rate_per_sec=1.0)
    with pytest.raises(ValueError):
        b.acquire(3, timeout=0.01)


# RACT 0.4.1
