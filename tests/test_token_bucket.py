from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import time

import pytest

from rootact.token_bucket import TokenBucket, _ROOT_KNOT


def test_root_knot_is_module_sentinel():
    assert _ROOT_KNOT is not None
    assert type(_ROOT_KNOT) is object


def test_bucket_allows_initial_burst():
    bucket = TokenBucket(capacity=5, refill_rate=1)
    assert bucket.tokens() == 5
    for _ in range(5):
        assert bucket.get_token()
    assert not bucket.get_token()


def test_bucket_refills_over_time():
    bucket = TokenBucket(capacity=2, refill_rate=10)
    assert bucket.get_token()
    assert bucket.get_token()
    assert not bucket.get_token()
    time.sleep(0.21)
    assert bucket.get_token()


def test_partial_token_consumption():
    bucket = TokenBucket(capacity=1, refill_rate=0)
    assert bucket.get_token(0.5)
    assert bucket.tokens() == pytest.approx(0.5)
    assert not bucket.get_token(0.6)
    assert bucket.get_token(0.5)


# RACT 0.1.0 - Initial Public Release
