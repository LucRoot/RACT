"""B-043: a refused connection fails fast and plainly.

J10 and J1b showed 16 s and `[WinError 10061]` three times before the
error. On Windows a refused connect to a closed loopback port is reported
only after about 2 s (4 s for "localhost"), so the loopback connect timeout
is short and a connection nothing answered gets one quick retry.
Read timeouts keep the full backoff.
"""

from __future__ import annotations

import socket
import time
from pathlib import Path

import httpx
import pytest

from ract.providers.local_http_provider import LocalHttpProvider
from ract.providers.openai_provider import OpenAICompatibleProvider
from ract.retry_policy import RetryConfig, RetryPolicy
from tests.test_headless import _ract
from tests.test_session_turn import _repo

RAW_OS_TEXT = ("WinError", "Errno", "actively refused it", "10061")


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_a_refused_local_server_fails_in_under_3_s(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"http://{host}:{_closed_port()}/v1"
    retries: list[tuple[int, int, str, float]] = []
    monkeypatch.setattr(
        "ract.providers.openai_provider.turn_context.on_retry",
        lambda *a: retries.append(a),
    )
    provider = LocalHttpProvider({"url": url, "model": "m"})

    started = time.perf_counter()
    result = provider.complete([{"role": "user", "content": "hi"}])
    elapsed = time.perf_counter() - started

    assert not result.is_ok()
    assert elapsed < 3.0, elapsed
    assert (
        result.error
        == f"Request failed: nothing is answering at {url} (connection refused)."
    )
    assert len(retries) == 1  # one quick retry
    attempt, limit, reason, wait = retries[0]
    assert (attempt, limit) == (1, 1) and wait <= 0.25
    assert url in reason
    for raw in RAW_OS_TEXT:
        assert raw not in reason and raw not in (result.error or "")


def test_the_cli_names_the_url_and_gives_the_hint(tmp_path: Path) -> None:
    url = f"http://127.0.0.1:{_closed_port()}"
    ws = _repo(tmp_path, url)

    started = time.perf_counter()
    result = _ract(ws, "-p", "fix add")
    elapsed = time.perf_counter() - started

    assert result.returncode == 6, result.stderr
    assert "nothing is answering at" in result.stderr and url in result.stderr
    assert "start your model server" in result.stderr
    assert result.stderr.count("trying once more in") == 1  # G-055 wording
    assert "retrying (1 of 1)" not in result.stderr
    for raw in RAW_OS_TEXT:
        assert raw not in result.stderr
    assert elapsed < 30  # process start included; the request part is checked above


def test_timeouts_keep_the_full_backoff() -> None:
    calls: list[float] = []
    policy = RetryPolicy(
        RetryConfig(max_retries=3, base_delay=1.0, max_delay=60.0, jitter=False)
    )

    def fail() -> None:
        raise httpx.ReadTimeout("slow")

    _, error = policy.execute(
        fail, lambda e: True, sleep=calls.append, quick=lambda e: False
    )
    assert isinstance(error, httpx.ReadTimeout)
    assert calls == [1.0, 2.0, 4.0]

    calls.clear()
    policy.execute(fail, lambda e: True, sleep=calls.append, quick=lambda e: True)
    assert calls == [0.25]


def test_what_counts_as_nothing_listening() -> None:
    local = OpenAICompatibleProvider({"url": "http://127.0.0.1:9/v1", "model": "m"})
    remote = OpenAICompatibleProvider(
        {"url": "https://api.example.invalid/v1", "model": "m"}
    )
    request = httpx.Request("POST", "http://x")

    assert local._nothing_listening(httpx.ConnectError("refused", request=request))
    assert local._nothing_listening(httpx.ConnectTimeout("t", request=request))
    assert not local._nothing_listening(httpx.ReadTimeout("t", request=request))
    assert remote._nothing_listening(httpx.ConnectError("dns", request=request))
    assert not remote._nothing_listening(httpx.ConnectTimeout("t", request=request))
    assert remote.describe_error(httpx.ReadTimeout("t", request=request)) == (
        "https://api.example.invalid/v1 did not answer within 60 s"
    )


def test_a_remote_server_keeps_its_connect_timeout() -> None:
    local = OpenAICompatibleProvider({"url": "http://localhost:8080/v1", "model": "m"})
    remote = OpenAICompatibleProvider(
        {"url": "https://api.example.invalid/v1", "model": "m"}
    )

    assert local.client.timeout.connect == 0.5
    assert remote.client.timeout.connect == 60.0
    assert local.client.timeout.read == 60.0
