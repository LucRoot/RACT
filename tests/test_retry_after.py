"""B-055: retry with jitter, ``Retry-After`` and plain messages.

A rate-limited or overloaded provider is waited for the right amount, the
user is told in plain words, and the retry stops after a bound. Cancel
ends a wait within a quarter second. A 4xx other than 408 and 429 is never
retried.
"""

from __future__ import annotations

import email.utils
import json
import random
import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from ract import turn_context
from ract.providers.openai_provider import OpenAICompatibleProvider
from ract.retry_policy import (
    MAX_RETRY_AFTER_S,
    RetryConfig,
    RetryPolicy,
    parse_retry_after,
)
from ract.session_events import EventStream
from ract.session_render import PlainRenderer
from ract.session_turn import hint_for

URL = "http://example.com/v1"
REQUEST = httpx.Request("POST", f"{URL}/chat/completions")
OK_BODY = {"choices": [{"message": {"content": "hi"}}]}


def _resp(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    if status == 200:
        return httpx.Response(200, json=OK_BODY, request=REQUEST)
    return httpx.Response(
        status,
        headers=headers or {},
        json={"error": {"message": f"fake {status}"}},
        request=REQUEST,
    )


def _provider(**extra: Any) -> OpenAICompatibleProvider:
    config: dict[str, Any] = {
        "url": URL,
        "model": "gpt-4o-mini",
        "api_key": "key",
        "max_retries": 3,
        "retry_delay": 1.0,
    }
    config.update(extra)
    return OpenAICompatibleProvider(config)


class _Recorder:
    """Captures on_retry calls and fake sleeps; no real waiting."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.retries: list[tuple[int, int, str, float]] = []
        self.sleeps: list[float] = []
        monkeypatch.setattr(
            "ract.providers.openai_provider.turn_context.on_retry",
            lambda *a: self.retries.append(a),
        )
        monkeypatch.setattr(
            "ract.retry_policy.time.sleep", lambda s: self.sleeps.append(s)
        )


def _complete(provider: OpenAICompatibleProvider, responses: list[Any]) -> Any:
    with patch.object(httpx.Client, "post", side_effect=responses) as post:
        result = provider.complete([{"role": "user", "content": "hello"}])
    return result, post.call_count


# ---------------------------------------------------------------- Retry-After parsing


def test_retry_after_seconds_are_read() -> None:
    assert parse_retry_after("8") == 8.0
    assert parse_retry_after("0") == 0.0


def test_retry_after_http_date_is_read_relative_to_now() -> None:
    now = 1_000_000.0
    when = email.utils.formatdate(now + 30, usegmt=True)
    assert parse_retry_after(when, now=now) == pytest.approx(30.0)


def test_retry_after_date_in_the_past_is_zero() -> None:
    now = 1_000_000.0
    past = email.utils.formatdate(now - 30, usegmt=True)
    assert parse_retry_after(past, now=now) == 0.0


@pytest.mark.parametrize("value", ["abc", "-5", "", None, "nan", "inf"])
def test_garbage_or_negative_retry_after_is_ignored(value: str | None) -> None:
    assert parse_retry_after(value) is None


def test_retry_after_bound_is_two_minutes() -> None:
    assert MAX_RETRY_AFTER_S == 120.0


# ---------------------------------------------------------------- provider retries


def test_429_with_retry_after_waits_what_the_server_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _Recorder(monkeypatch)
    result, calls = _complete(
        _provider(),
        [_resp(429, {"Retry-After": "2"}), _resp(200)],
    )
    assert result.is_ok()
    assert calls == 2
    assert rec.retries == [(1, 3, "the provider is rate-limiting", 2.0)]
    assert rec.sleeps == [0.25] * 8  # the wait runs in quarter-second slices


def test_429_with_http_date_waits_about_the_right_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _Recorder(monkeypatch)
    when = email.utils.formatdate(time.time() + 10, usegmt=True)
    result, calls = _complete(_provider(), [_resp(429, {"Retry-After": when}), _resp(200)])
    assert result.is_ok() and calls == 2
    assert 8.0 <= rec.retries[0][3] <= 10.0


@pytest.mark.parametrize("value", ["abc", "-5"])
def test_unusable_retry_after_falls_back_to_backoff(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = _Recorder(monkeypatch)
    result, calls = _complete(_provider(), [_resp(429, {"Retry-After": value}), _resp(200)])
    assert result.is_ok() and calls == 2
    # Backoff for the first retry is base 1.0 s with a jitter factor in [0.5, 1.0).
    assert 0.5 <= rec.retries[0][3] < 1.0


def test_retry_after_over_the_bound_stops_without_sleeping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _Recorder(monkeypatch)
    result, calls = _complete(_provider(), [_resp(429, {"Retry-After": "99999"})])
    assert not result.is_ok()
    assert calls == 1
    assert rec.retries == [] and rec.sleeps == []
    assert "HTTP 429" in (result.error or "")


def test_503_three_times_then_success_has_jittered_growing_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _Recorder(monkeypatch)
    result, calls = _complete(
        _provider(),
        [_resp(503), _resp(503), _resp(503), _resp(200)],
    )
    assert result.is_ok() and calls == 4
    waits = [w[3] for w in rec.retries]
    assert len(waits) == 3
    # Exponential base 1, 2, 4 with the jitter factor in [0.5, 1.0).
    for wait, base in zip(waits, [1.0, 2.0, 4.0], strict=True):
        assert 0.5 * base <= wait < base
    assert len(set(waits)) == 3


def test_connection_reset_is_retried_once_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _Recorder(monkeypatch)
    reset = httpx.ReadError("connection reset", request=REQUEST)
    result, calls = _complete(_provider(), [reset, _resp(200)])
    assert result.is_ok() and calls == 2
    assert len(rec.retries) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_are_never_retried(
    status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = _Recorder(monkeypatch)
    result, calls = _complete(_provider(), [_resp(status)])
    assert not result.is_ok()
    assert calls == 1
    assert rec.retries == []
    assert f"HTTP {status}" in (result.error or "")


def test_408_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _Recorder(monkeypatch)
    result, calls = _complete(_provider(), [_resp(408), _resp(200)])
    assert result.is_ok() and calls == 2
    assert len(rec.retries) == 1


def test_bound_reached_gives_a_clean_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _Recorder(monkeypatch)
    result, calls = _complete(_provider(max_retries=2), [_resp(503) for _ in range(3)])
    assert not result.is_ok()
    assert calls == 3
    assert len(rec.retries) == 2
    assert "HTTP 503" in (result.error or "")


def test_a_200_with_retry_after_is_not_a_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _Recorder(monkeypatch)
    result, calls = _complete(_provider(), [_resp(200, {"Retry-After": "5"})])
    assert result.is_ok() and calls == 1
    assert rec.retries == []


# ---------------------------------------------------------------- cancel


def test_cancel_during_a_retry_wait_ends_it_and_makes_no_new_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel = turn_context.CancelSignal()
    sleeps: list[float] = []

    def sleep_then_cancel(seconds: float) -> None:
        sleeps.append(seconds)
        cancel.set()

    monkeypatch.setattr("ract.retry_policy.time.sleep", sleep_then_cancel)
    turn_context.bind(cancel)
    try:
        result, calls = _complete(
            _provider(), [_resp(429, {"Retry-After": "30"}), _resp(200)]
        )
    finally:
        turn_context.bind(None)
    assert not result.is_ok()
    assert calls == 1
    assert sum(sleeps) <= 0.3


# ---------------------------------------------------------------- stream


class _Body(httpx.SyncByteStream):
    """A body that yields some bytes, then fails as a reset would."""

    def __init__(self, parts: list[bytes], then: Exception | None) -> None:
        self._parts = parts
        self._then = then

    def __iter__(self) -> Iterator[bytes]:
        yield from self._parts
        if self._then is not None:
            raise self._then


def _stream_provider(handler: Any) -> OpenAICompatibleProvider:
    provider = _provider()
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    return provider


def _sse(text: str) -> bytes:
    chunk = {"choices": [{"delta": {"content": text}, "finish_reason": None}]}
    return f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()


def test_stream_retries_a_429_before_the_first_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _Recorder(monkeypatch)
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, request=request)
        return httpx.Response(200, stream=_Body([_sse("hello")], None), request=request)

    provider = _stream_provider(handler)
    results = list(provider.complete_stream([{"role": "user", "content": "x"}]))
    assert len(seen) == 2
    assert [r.unwrap()["choices"][0]["delta"]["content"] for r in results] == ["hello"]
    assert rec.retries == [(1, 3, "the provider is rate-limiting", 1.0)]


def test_stream_reset_after_text_reached_the_user_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = _Recorder(monkeypatch)
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        chunk = _sse("partial").split(b"\n\n")[0] + b"\n\n"  # no [DONE]: the reset comes first
        body = _Body([chunk], httpx.ReadError("connection reset", request=request))
        return httpx.Response(200, stream=body, request=request)

    provider = _stream_provider(handler)
    results = list(provider.complete_stream([{"role": "user", "content": "x"}]))
    assert len(seen) == 1
    assert rec.retries == []
    assert any(not r.is_ok() for r in results)


# ---------------------------------------------------------------- plain wording


def test_the_rate_limit_retry_line_says_what_and_when() -> None:
    out: list[str] = []
    stream = EventStream(session="s-b055")
    stream.subscribe(PlainRenderer(out.append))
    stream.emit(
        "agent.retry",
        {
            "attempt": 1,
            "max": 3,
            "reason": "the provider is rate-limiting",
            "wait_ms": 8000,
        },
        turn=1,
    )
    assert "".join(out) == (
        "  the provider is rate-limiting; trying again in 8 s (attempt 2 of 4)\n"
    )


def test_the_rate_limit_hint_names_the_bound_and_the_next_step() -> None:
    hint = hint_for("HTTP 429: rate limited")
    assert "rate_limit" in hint
    assert "switch provider" in hint
    assert "wait" in hint


# ---------------------------------------------------------------- jitter


def test_jitter_draw_is_injectable_and_bounded() -> None:
    low = RetryPolicy(RetryConfig(3, 1.0, 60.0, jitter=True, rand=lambda: 0.0))
    mid = RetryPolicy(RetryConfig(3, 1.0, 60.0, jitter=True, rand=lambda: 0.5))
    assert low.calculate_delay(2) == pytest.approx(1.0)  # 2.0 * 0.5
    assert mid.calculate_delay(2) == pytest.approx(1.5)  # 2.0 * 0.75


def test_jitter_never_exceeds_the_cap() -> None:
    policy = RetryPolicy(RetryConfig(9, 1.0, 60.0, jitter=True, rand=lambda: 0.999))
    assert policy.calculate_delay(9) < 60.0 + 1e-9


def test_consecutive_jittered_waits_differ_for_a_seeded_source() -> None:
    rng = random.Random(7)
    policy = RetryPolicy(RetryConfig(3, 1.0, 60.0, jitter=True, rand=rng.random))
    waits = [policy.calculate_delay(n) for n in (1, 2, 3)]
    assert all(a != b for a, b in zip(waits, waits[1:], strict=False))
