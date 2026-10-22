"""S-025: a key from the operator's environment goes only to its own host.

The provider sent OPENAI_API_KEY to whatever URL the project's ract.yaml
named, so a cloned repository could collect it. And `api_key: ${VAR}`, the
form the presets and `ract doctor` use, was never expanded: the literal text
was sent, so preset cloud providers could not authenticate.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr
from typing import Any

import httpx
import pytest

from ract.providers.openai_provider import OpenAICompatibleProvider, key_hosts

SECRET = "sk-" + "envSECRETvalue1234567890"


def _captured(provider: OpenAICompatibleProvider) -> list[dict[str, Any]]:
    """Route the provider's requests to a mock transport; return what it saw."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {"host": request.url.host, "auth": request.headers.get("authorization")}
        )
        body = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        return httpx.Response(200, json=body)

    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    return seen


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("RACT_KEY_HOSTS", raising=False)


@pytest.mark.parametrize(
    "config",
    [
        {"url": "https://collector.example.invalid/v1"},
        {"url": "https://collector.example.invalid/v1", "api_key": "${OPENAI_API_KEY}"},
        {"base_url": "https://collector.example.invalid/v1"},
    ],
)
def test_an_environment_key_never_goes_to_a_host_the_config_names(
    config: dict[str, Any],
) -> None:
    provider = OpenAICompatibleProvider(config)
    seen = _captured(provider)
    err = io.StringIO()
    with redirect_stderr(err):
        provider.complete([{"role": "user", "content": "hi"}])
        provider.complete([{"role": "user", "content": "hi"}])
    assert seen and all(SECRET not in (s["auth"] or "") for s in seen)
    notice = err.getvalue()
    assert notice.count("OPENAI_API_KEY was not sent to collector.example.invalid") == 1
    assert SECRET not in notice


def test_an_environment_key_reaches_its_own_host() -> None:
    for config in (
        {},
        {"url": "https://api.openai.com/v1", "api_key": "${OPENAI_API_KEY}"},
    ):
        provider = OpenAICompatibleProvider(config)
        seen = _captured(provider)
        provider.complete([{"role": "user", "content": "hi"}])
        assert seen[0]["host"] == "api.openai.com"
        assert seen[0]["auth"] == f"Bearer {SECRET}"


def test_a_preset_key_variable_is_expanded_for_its_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The literal "${ANTHROPIC_API_KEY}" used to be sent as the key."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-" + "value")
    provider = OpenAICompatibleProvider(
        {"url": "https://api.anthropic.com/v1", "api_key": "${ANTHROPIC_API_KEY}"}
    )
    seen = _captured(provider)
    provider.complete([{"role": "user", "content": "hi"}])
    assert seen[0]["auth"] == "Bearer ak-value"


def test_the_operator_can_pair_a_key_with_a_host_outside_the_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = {"url": "https://gateway.example.invalid/v1"}
    monkeypatch.setenv("RACT_KEY_HOSTS", "OPENAI_API_KEY=gateway.example.invalid")
    provider = OpenAICompatibleProvider(config)
    seen = _captured(provider)
    provider.complete([{"role": "user", "content": "hi"}])
    assert seen[0]["auth"] == f"Bearer {SECRET}"
    monkeypatch.delenv("RACT_KEY_HOSTS")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example.invalid/v1")
    assert "gateway.example.invalid" in key_hosts("OPENAI_API_KEY")


def test_a_literal_key_in_the_config_goes_where_the_config_says() -> None:
    provider = OpenAICompatibleProvider(
        {"url": "https://gateway.example.invalid/v1", "api_key": "written-in-config"}
    )
    seen = _captured(provider)
    provider.complete([{"role": "user", "content": "hi"}])
    assert seen[0]["auth"] == "Bearer written-in-config"


def test_key_hosts_come_only_from_outside_the_project() -> None:
    hosts = key_hosts("OPENAI_API_KEY")
    assert hosts == {"api.openai.com"}
    assert json.dumps(sorted(key_hosts("NOT_A_KNOWN_VAR"))) == "[]"
