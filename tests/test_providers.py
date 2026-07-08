__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the provider adapter layer."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from rootact.providers.local_http_provider import LocalHttpProvider
from rootact.providers.openai_provider import OpenAICompatibleProvider
from rootact.providers.router import ProviderRouter


class _FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data
        self.text = json.dumps(json_data)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = self.status_code
            mock_response.text = self.text
            raise httpx.HTTPStatusError(
                "bad", request=MagicMock(spec=httpx.Request), response=mock_response
            )


def test_openai_provider_returns_rooted_response():
    provider = OpenAICompatibleProvider(
        {"url": "http://example.com/v1", "model": "gpt-4o-mini", "api_key": "key"}
    )
    fake = _FakeResponse(200, {"choices": [{"message": {"content": "hi"}}]})
    with patch.object(httpx.Client, "post", return_value=fake):
        result = provider.complete([{"role": "user", "content": "hello"}])
    assert result.is_ok()
    assert result.unwrap()["choices"][0]["message"]["content"] == "hi"


def test_openai_provider_rooted_error_on_http_error():
    provider = OpenAICompatibleProvider(
        {"url": "http://example.com/v1", "model": "gpt-4o-mini", "api_key": "key"}
    )
    fake = _FakeResponse(500, {})
    with patch.object(httpx.Client, "post", return_value=fake):
        result = provider.complete([{"role": "user", "content": "hello"}])
    assert not result.is_ok()


def test_router_selects_provider_by_hint():
    router = ProviderRouter(
        {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        }
    )
    adapter_rooted = router.select_for_hint("chat")
    assert adapter_rooted.is_ok()
    assert adapter_rooted.unwrap().name == "local_http"


def test_router_returns_error_when_no_providers():
    router = ProviderRouter({})
    adapter_rooted = router.select_for_hint("chat")
    assert not adapter_rooted.is_ok()
    assert "No providers" in (adapter_rooted.error or "")


@pytest.fixture
def isolated_registry():
    """Snapshot and restore the global adapter registry around a test."""
    from rootact.providers.router import _ADAPTER_CLASSES

    snapshot = dict(_ADAPTER_CLASSES)
    yield
    _ADAPTER_CLASSES.clear()
    _ADAPTER_CLASSES.update(snapshot)


def test_register_custom_adapter(isolated_registry):
    from rootact.providers.base import ProviderAdapter
    from rootact.providers.router import register_adapter
    from rootact.rooted import Rooted

    class DummyAdapter(ProviderAdapter):
        def __init__(self, config: dict[str, Any]) -> None:
            super().__init__(config)
            self.config = config

        @property
        def name(self) -> str:
            return "dummy"

        def models(self) -> list[str]:
            return ["dummy-model"]

        def capabilities(self) -> set[str]:
            return {"chat"}

        def complete(
            self,
            messages: list[dict[str, str]],
            *,
            model: str | None = None,
            max_tokens: int = 512,
            temperature: float = 0.3,
        ) -> Rooted[dict[str, Any]]:
            return Rooted(
                value={"choices": [{"message": {"content": "ok"}}]},
                assumption="ok",
                confidence=1.0,
            )

    register_adapter("dummy", DummyAdapter)
    router = ProviderRouter({"d1": {"adapter": "dummy"}})
    result = router.get_adapter("d1")
    assert result.is_ok()
    assert result.unwrap().name == "dummy"


def test_local_http_provider_omits_auth_header():
    """Local servers should not receive an Authorization header."""
    provider = LocalHttpProvider(
        {"url": "http://127.0.0.1:11434/v1", "model": "nemotron"}
    )
    fake = _FakeResponse(200, {"choices": [{"message": {"content": "hi"}}]})
    captured: dict[str, Any] = {}

    def capture_post(url, *, headers=None, json=None, **_kwargs):
        captured["headers"] = dict(headers or {})
        captured["json"] = json
        return fake

    with patch.object(provider.client, "post", side_effect=capture_post):
        result = provider.complete([{"role": "user", "content": "hello"}])

    assert result.is_ok()
    assert "Authorization" not in captured["headers"]
    assert captured["headers"].get("Content-Type") == "application/json"


def test_openai_provider_retries_then_succeeds():
    provider = OpenAICompatibleProvider(
        {
            "url": "http://example.com/v1",
            "model": "gpt-4o-mini",
            "api_key": "key",
            "max_retries": 3,
            "retry_delay": 0.0,
        }
    )
    ok = _FakeResponse(200, {"choices": [{"message": {"content": "hi"}}]})
    fail = _FakeResponse(503, {"error": "overloaded"})

    with patch.object(httpx.Client, "post", side_effect=[fail, fail, ok]) as mock_post:
        result = provider.complete([{"role": "user", "content": "hello"}])

    assert result.is_ok()
    assert result.unwrap()["choices"][0]["message"]["content"] == "hi"
    assert mock_post.call_count == 3


def test_openai_provider_does_not_retry_4xx():
    provider = OpenAICompatibleProvider(
        {
            "url": "http://example.com/v1",
            "model": "gpt-4o-mini",
            "api_key": "key",
            "max_retries": 3,
            "retry_delay": 0.0,
        }
    )
    fail = _FakeResponse(400, {"error": "bad request"})

    with patch.object(httpx.Client, "post", return_value=fail) as mock_post:
        result = provider.complete([{"role": "user", "content": "hello"}])

    assert not result.is_ok()
    assert "400" in (result.error or "")
    assert mock_post.call_count == 1


class _FakeStream:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        return iter(self._lines)

    def raise_for_status(self) -> None:
        pass


def _stream_line(content: str) -> str:
    chunk = {
        "choices": [{"delta": {"content": content}, "index": 0, "finish_reason": None}]
    }
    return f"data: {json.dumps(chunk)}"


def test_openai_provider_streams_chunks():
    provider = OpenAICompatibleProvider(
        {"url": "http://example.com/v1", "model": "gpt-4o-mini", "api_key": "key"}
    )
    lines = [
        _stream_line("Hello"),
        _stream_line(", "),
        _stream_line("world!"),
        "data: [DONE]",
    ]
    with patch.object(provider.client, "stream", return_value=_FakeStream(lines)):
        chunks = list(provider.complete_stream([{"role": "user", "content": "hi"}]))

    assert all(c.is_ok() for c in chunks)
    contents = [c.unwrap()["choices"][0]["delta"]["content"] for c in chunks]
    assert "".join(contents) == "Hello, world!"


def test_openai_stream_skips_malformed_lines():
    provider = OpenAICompatibleProvider(
        {"url": "http://example.com/v1", "model": "gpt-4o-mini", "api_key": "key"}
    )
    lines = [
        "",
        ": comment",
        _stream_line("ok"),
        "data: not-json",
        "data: [DONE]",
    ]
    with patch.object(provider.client, "stream", return_value=_FakeStream(lines)):
        chunks = list(provider.complete_stream([{"role": "user", "content": "hi"}]))

    assert len(chunks) == 1
    assert chunks[0].unwrap()["choices"][0]["delta"]["content"] == "ok"


def test_local_http_provider_streams_without_auth():
    provider = LocalHttpProvider(
        {"url": "http://127.0.0.1:11434/v1", "model": "nemotron"}
    )
    captured: dict[str, Any] = {}

    def capture_stream(method, url, *, headers=None, json=None, **_kwargs):
        captured["headers"] = dict(headers or {})
        captured["json"] = json
        return _FakeStream([_stream_line("hi"), "data: [DONE]"])

    with patch.object(provider.client, "stream", side_effect=capture_stream):
        chunks = list(provider.complete_stream([{"role": "user", "content": "hello"}]))

    assert len(chunks) == 1
    assert "Authorization" not in captured["headers"]
    assert captured["json"].get("stream") is True


def test_local_http_provider_health_check_failure():
    provider = LocalHttpProvider({"url": "http://127.0.0.1:11434/v1"})
    with patch.object(provider.client, "get", side_effect=httpx.ConnectError("down")):
        assert provider.health_check() is False


def test_local_http_provider_close_is_safe():
    provider = LocalHttpProvider({"url": "http://127.0.0.1:11434/v1"})
    provider.close()
    provider.close()


def test_streaming_capability_advertised():
    provider = OpenAICompatibleProvider({"url": "http://example.com/v1"})
    assert "streaming" in provider.capabilities()
    local = LocalHttpProvider({"url": "http://127.0.0.1:11434/v1"})
    assert "streaming" in local.capabilities()


def test_router_uses_capability_scores_to_select_best_provider():
    router = ProviderRouter(
        {
            "cheap": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
                "capabilities": ["chat", "fast"],
                "score_weights": {"chat": 1.0, "fast": 1.0},
            },
            "strong": {
                "adapter": "openai",
                "url": "http://example.com/v1",
                "model": "gpt-4o-mini",
                "api_key": "key",
                "capabilities": ["chat", "code", "frontier"],
                "score_weights": {"chat": 1.0, "code": 1.0, "frontier": 1.0},
            },
        }
    )
    adapter_rooted = router.select_for_hint("code")
    assert adapter_rooted.is_ok()
    # The openai slot scores higher for code because it advertises code.
    assert adapter_rooted.unwrap().name == "openai_compatible"


def test_router_fallback_chain_orders_by_score():
    router = ProviderRouter(
        {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
                "capabilities": ["chat", "fast"],
                "score_weights": {"chat": 1.0, "fast": 1.0},
            },
            "openai": {
                "adapter": "openai",
                "url": "http://example.com/v1",
                "model": "gpt-4o-mini",
                "api_key": "key",
                "capabilities": ["chat", "code", "frontier"],
                "score_weights": {"chat": 2.0, "code": 2.0, "frontier": 2.0},
            },
        }
    )
    chain = router.fallback_chain("chat", max_attempts=2)
    assert len(chain) == 2
    assert chain[0].unwrap().name == "openai_compatible"
    assert chain[1].unwrap().name == "local_http"


def test_router_health_check_returns_true_for_healthy_adapter():
    router = ProviderRouter(
        {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        }
    )
    ok = MagicMock(spec=httpx.Response)
    ok.status_code = 200
    ok.raise_for_status.return_value = None
    with patch.object(httpx.Client, "get", return_value=ok):
        result = router.health_check("local")
    assert result.is_ok()
    assert result.unwrap() is True


def test_router_health_check_for_unknown_slot_returns_false():
    router = ProviderRouter({})
    result = router.health_check("missing")
    assert not result.is_ok()
    assert result.unwrap() is False


def test_openai_provider_health_check_success():
    provider = OpenAICompatibleProvider(
        {"url": "https://api.openai.com/v1", "api_key": "test-key", "model": "gpt-4o"}
    )
    ok = MagicMock(spec=httpx.Response)
    ok.status_code = 200
    ok.raise_for_status.return_value = None
    with patch.object(httpx.Client, "get", return_value=ok) as mock_get:
        assert provider.health_check() is True
    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.openai.com/v1/models"
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"


def test_openai_provider_health_check_failure():
    provider = OpenAICompatibleProvider(
        {"url": "https://api.openai.com/v1", "api_key": "test-key", "model": "gpt-4o"}
    )
    with patch.object(
        httpx.Client, "get", side_effect=httpx.ConnectError("unreachable")
    ):
        assert provider.health_check() is False


def test_local_http_provider_health_check_omits_auth():
    provider = LocalHttpProvider(
        {"url": "http://127.0.0.1:11434/v1", "model": "nemotron"}
    )
    ok = MagicMock(spec=httpx.Response)
    ok.status_code = 200
    ok.raise_for_status.return_value = None
    with patch.object(httpx.Client, "get", return_value=ok) as mock_get:
        assert provider.health_check() is True
    args, kwargs = mock_get.call_args
    assert "Authorization" not in kwargs.get("headers", {})


def test_openai_provider_reports_cost_when_configured():
    provider = OpenAICompatibleProvider(
        {
            "url": "http://example.com/v1",
            "model": "gpt-4o-mini",
            "api_key": "key",
            "input_cost_per_1k": 0.005,
            "output_cost_per_1k": 0.015,
        }
    )
    assert provider.input_cost_per_1k() == 0.005
    assert provider.output_cost_per_1k() == 0.015


def test_openai_provider_complete_missing_choices_returns_error():
    provider = OpenAICompatibleProvider(
        {"url": "http://example.com/v1", "model": "gpt-4o-mini", "api_key": "key"}
    )
    fake = _FakeResponse(200, {"choices": []})
    with patch.object(httpx.Client, "post", return_value=fake):
        result = provider.complete([{"role": "user", "content": "hello"}])
    assert not result.is_ok()
    assert "missing choices" in (result.error or "").lower()


def test_openai_provider_complete_unexpected_error_after_retries():
    provider = OpenAICompatibleProvider(
        {
            "url": "http://example.com/v1",
            "model": "gpt-4o-mini",
            "api_key": "key",
            "max_retries": 2,
            "retry_delay": 0.0,
        }
    )
    with patch.object(httpx.Client, "post", side_effect=ValueError("boom")):
        result = provider.complete([{"role": "user", "content": "hello"}])
    assert not result.is_ok()
    assert "unexpected error" in (result.error or "").lower()


def test_openai_provider_retries_on_429_when_enabled():
    provider = OpenAICompatibleProvider(
        {
            "url": "http://example.com/v1",
            "model": "gpt-4o-mini",
            "api_key": "key",
            "max_retries": 2,
            "retry_delay": 0.0,
            "retry_on_429": True,
        }
    )
    ok = _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})
    fail = _FakeResponse(429, {"error": "rate limited"})
    with patch.object(httpx.Client, "post", side_effect=[fail, ok]) as mock_post:
        result = provider.complete([{"role": "user", "content": "hello"}])
    assert result.is_ok()
    assert mock_post.call_count == 2


def test_openai_provider_stream_http_status_error():
    provider = OpenAICompatibleProvider(
        {"url": "http://example.com/v1", "model": "gpt-4o-mini", "api_key": "key"}
    )

    def raise_429(*args, **kwargs):
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 429
        mock_response.text = "rate limited"
        raise httpx.HTTPStatusError(
            "rate", request=MagicMock(spec=httpx.Request), response=mock_response
        )

    with patch.object(provider.client, "stream", side_effect=raise_429):
        chunks = list(provider.complete_stream([{"role": "user", "content": "hi"}]))
    assert len(chunks) == 1
    assert not chunks[0].is_ok()
    assert "429" in (chunks[0].error or "")


def test_openai_provider_stream_request_error():
    provider = OpenAICompatibleProvider(
        {"url": "http://example.com/v1", "model": "gpt-4o-mini", "api_key": "key"}
    )
    with patch.object(
        provider.client, "stream", side_effect=httpx.ConnectError("down")
    ):
        chunks = list(provider.complete_stream([{"role": "user", "content": "hi"}]))
    assert len(chunks) == 1
    assert not chunks[0].is_ok()
    assert "down" in (chunks[0].error or "")


def test_openai_provider_stream_unknown_sse_line():
    provider = OpenAICompatibleProvider(
        {"url": "http://example.com/v1", "model": "gpt-4o-mini", "api_key": "key"}
    )
    lines = ["unexpected line without data prefix", "data: [DONE]"]
    with patch.object(provider.client, "stream", return_value=_FakeStream(lines)):
        chunks = list(provider.complete_stream([{"role": "user", "content": "hi"}]))
    assert len(chunks) == 1
    assert not chunks[0].is_ok()
    assert "unexpected sse line" in (chunks[0].error or "").lower()


def test_router_falls_back_when_no_provider_matches_hint():
    router = ProviderRouter(
        {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
                "capabilities": ["chat"],
                "score_weights": {"chat": 1.0},
            },
        }
    )
    adapter_rooted = router.select_for_hint("embed")
    assert adapter_rooted.is_ok()
    assert adapter_rooted.unwrap().name == "local_http"


def test_router_get_adapter_for_unknown_slot_returns_error():
    router = ProviderRouter(
        {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            }
        }
    )
    result = router.get_adapter("missing")
    assert not result.is_ok()
    assert "not configured" in (result.error or "").lower()


def test_router_get_adapter_for_unknown_adapter_returns_error():
    router = ProviderRouter(
        {"bad": {"adapter": "not_real", "url": "http://x", "model": "x"}}
    )
    result = router.get_adapter("bad")
    assert not result.is_ok()
    assert "unknown provider adapter" in (result.error or "").lower()


def test_router_select_with_no_providers_returns_error():
    router = ProviderRouter({})
    result = router.select_for_hint("chat")
    assert not result.is_ok()
    assert "no providers" in (result.error or "").lower()


def test_router_fallback_chain_empty_providers_returns_empty():
    router = ProviderRouter({})
    assert router.fallback_chain("chat") == []


def test_router_health_check_catches_adapter_exception():
    router = ProviderRouter(
        {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            }
        }
    )
    adapter = router.get_adapter("local").unwrap()
    with patch.object(adapter, "health_check", side_effect=RuntimeError("boom")):
        result = router.health_check("local")
    assert not result.is_ok()
    assert result.unwrap() is False


def test_router_uses_default_capabilities_when_adapter_returns_empty():
    """Adapter reports no capabilities; router falls back to defaults."""
    router = ProviderRouter(
        {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
                "capabilities": [],
            }
        }
    )
    result = router.select_for_hint("local")
    assert result.is_ok()
    assert result.unwrap().name == "local_http"


def test_router_select_fallback_to_first_when_registry_empty():
    """If no providers register (e.g. unknown adapter), select first configured."""
    router = ProviderRouter({"bad": {"adapter": "unknown", "url": "http://x"}})
    result = router.select_for_hint("chat")
    assert not result.is_ok()


def test_router_fallback_chain_fallback_to_first_when_registry_empty():
    router = ProviderRouter({"bad": {"adapter": "unknown", "url": "http://x"}})
    chain = router.fallback_chain("chat")
    assert len(chain) == 1
    assert not chain[0].is_ok()
