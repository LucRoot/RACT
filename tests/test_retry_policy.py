# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import random

import pytest

from ract.retry_policy import RetryConfig, RetryPolicy


def test_retry_policy_basic():
    config = RetryConfig(max_retries=3, base_delay=0.1, max_delay=0.5, jitter=False)
    policy = RetryPolicy(config=config)
    assert policy.should_retry(0) is True
    assert policy.should_retry(3) is False


def test_calculate_delay_monotonic():
    config = RetryConfig(max_retries=3, base_delay=0.1, max_delay=0.5, jitter=False)
    policy = RetryPolicy(config=config)
    assert policy.calculate_delay(1) == 0.1
    assert policy.calculate_delay(2) == 0.2
    assert policy.calculate_delay(3) == 0.4


def test_calculate_delay_with_jitter_variability():
    config = RetryConfig(max_retries=3, base_delay=0.1, max_delay=0.5, jitter=True)
    policy = RetryPolicy(config=config)
    random.seed(42)
    delay = policy.calculate_delay(1)
    assert 0.0 <= delay <= 1.0


def test_execute_returns_value_on_success():
    config = RetryConfig(max_retries=2, base_delay=0.0, max_delay=0.0, jitter=False)
    policy = RetryPolicy(config=config)
    value, error = policy.execute(lambda: "ok", lambda _exc: True)
    assert value == "ok"
    assert error is None


def test_execute_retries_then_succeeds():
    config = RetryConfig(max_retries=3, base_delay=0.0, max_delay=0.0, jitter=False)
    policy = RetryPolicy(config=config)
    calls = []

    def fn():
        calls.append(len(calls))
        if len(calls) < 3:
            raise RuntimeError("transient")
        return "ok"

    value, error = policy.execute(fn, lambda _exc: True)
    assert value == "ok"
    assert error is None
    assert len(calls) == 3


def test_execute_gives_up_on_non_retryable_error():
    config = RetryConfig(max_retries=3, base_delay=0.0, max_delay=0.0, jitter=False)
    policy = RetryPolicy(config=config)
    calls = []

    def fn():
        calls.append(1)
        raise ValueError("permanent")

    value, error = policy.execute(fn, lambda exc: isinstance(exc, RuntimeError))
    assert value is None
    assert isinstance(error, ValueError)
    assert len(calls) == 1


def test_execute_uses_custom_sleep():
    config = RetryConfig(max_retries=2, base_delay=1.0, max_delay=10.0, jitter=False)
    policy = RetryPolicy(config=config)
    sleeps = []

    def fn():
        raise RuntimeError("transient")

    value, error = policy.execute(fn, lambda _exc: True, sleep=sleeps.append)
    assert value is None
    assert isinstance(error, RuntimeError)
    assert sleeps == [1.0, 2.0]


def test_retry_config_rejects_negative_values():
    with pytest.raises(ValueError):
        RetryConfig(max_retries=-1, base_delay=0.1, max_delay=0.5, jitter=False)
    with pytest.raises(ValueError):
        RetryConfig(max_retries=1, base_delay=-0.1, max_delay=0.5, jitter=False)
    with pytest.raises(ValueError):
        RetryConfig(max_retries=1, base_delay=0.1, max_delay=-0.5, jitter=False)


def test_calculate_delay_zero_for_first_attempt():
    config = RetryConfig(max_retries=3, base_delay=0.1, max_delay=1.0, jitter=False)
    policy = RetryPolicy(config=config)
    assert policy.calculate_delay(0) == 0.0


# RACT 0.1.1 - Trust and tooling
