"""Output-cap behavior for OpenAI-compatible and local HTTP providers."""

from __future__ import annotations

import pytest

from ract.providers.local_http_provider import LocalHttpProvider
from ract.providers.openai_provider import OpenAICompatibleProvider
from ract.providers.router import ProviderRouter

MSGS = [{"role": "user", "content": "hi"}]


def _payload(provider, requested: int = 1024) -> dict:
    return provider._build_payload(
        MSGS, model=None, max_tokens=requested, temperature=0.2, stream=False
    )


def test_hosted_provider_uses_the_callers_cap_by_default():
    provider = OpenAICompatibleProvider({"url": "http://x/v1", "api_key": "k"})
    assert _payload(provider, 1024)["max_tokens"] == 1024


def test_local_provider_sends_no_cap_by_default():
    """Regression: a hidden 1024 cap cut a reasoning model's plan off mid-JSON."""
    provider = LocalHttpProvider({"url": "http://127.0.0.1:8080/v1"})
    assert "max_tokens" not in _payload(provider, 1024)


def test_configured_cap_overrides_callers_value_on_local():
    provider = LocalHttpProvider({"url": "http://x/v1", "max_tokens": 8192})
    assert _payload(provider, 1024)["max_tokens"] == 8192


def test_configured_cap_overrides_callers_value_on_hosted():
    provider = OpenAICompatibleProvider(
        {"url": "http://x/v1", "api_key": "k", "max_tokens": 300}
    )
    assert _payload(provider, 1024)["max_tokens"] == 300


@pytest.mark.parametrize("value", ["none", "None", "unlimited", "off", 0, None])
def test_cap_can_be_removed_explicitly_on_hosted(value):
    provider = OpenAICompatibleProvider(
        {"url": "http://x/v1", "api_key": "k", "max_tokens": value}
    )
    assert "max_tokens" not in _payload(provider, 1024)


def test_numeric_string_cap_is_accepted():
    provider = LocalHttpProvider({"url": "http://x/v1", "max_tokens": "4096"})
    assert _payload(provider)["max_tokens"] == 4096


@pytest.mark.parametrize("value", ["lots", 1.5, True, [1]])
def test_invalid_cap_is_rejected(value):
    with pytest.raises(ValueError, match="max_tokens"):
        LocalHttpProvider({"url": "http://x/v1", "max_tokens": value})


def test_router_reports_invalid_cap_as_a_slot_error_not_a_crash():
    router = ProviderRouter(
        {"bolt": {"adapter": "local_http", "url": "http://x/v1", "max_tokens": "lots"}}
    )
    result = router.get_adapter("bolt")
    assert not result.is_ok()
    assert "misconfigured" in result.error and "max_tokens" in result.error


def test_local_provider_has_a_long_default_timeout():
    """A 60 s timeout retried a 70B reasoning generation from scratch."""
    assert LocalHttpProvider({"url": "http://x/v1"}).timeout >= 300


def test_local_provider_timeout_can_still_be_set():
    assert LocalHttpProvider({"url": "http://x/v1", "timeout": 30}).timeout == 30.0


def test_payload_keeps_stream_and_model_fields():
    provider = LocalHttpProvider({"url": "http://x/v1", "model": "north"})
    payload = provider._build_payload(
        MSGS, model=None, max_tokens=10, temperature=0.1, stream=True
    )
    assert payload["stream"] is True
    assert payload["model"] == "north"
    assert payload["messages"] == MSGS
