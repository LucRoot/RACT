"""B-074 FOUND (S2): ``api_key: ${VAR}`` with VAR unset names VAR and sends nothing.

Before, the request went out without the key and the turn failed with no cause.
"""

from __future__ import annotations

from typing import Any

import pytest

from ract.providers.local_http_provider import LocalHttpProvider
from ract.providers.openai_provider import OpenAICompatibleProvider
from tests.fixtures.fake_model_server import Scenario

VAR = "RACT_TEST_MISSING_KEY_VARIABLE"
REPLY = {"turns": [{"reply": {"kind": "text", "content": "hello"}}]}


@pytest.fixture(autouse=True)
def _unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(VAR, raising=False)


@pytest.mark.parametrize("adapter", [OpenAICompatibleProvider, LocalHttpProvider])
def test_complete_names_the_variable_and_sends_nothing(
    adapter: Any, fake_model_server: Any
) -> None:
    server = fake_model_server(Scenario.from_dict(REPLY))
    provider = adapter({"url": server.base_url, "model": "m", "api_key": f"${{{VAR}}}"})

    result = provider.complete([{"role": "user", "content": "hi"}])

    assert not result.is_ok()
    assert VAR in result.error and "not set" in result.error
    assert VAR in result.hint
    assert server.chat_requests == []


def test_the_stream_names_the_variable_and_sends_nothing(
    fake_model_server: Any,
) -> None:
    server = fake_model_server(Scenario.from_dict(REPLY))
    provider = OpenAICompatibleProvider(
        {"url": server.base_url, "model": "m", "api_key": f"${{{VAR}}}"}
    )

    chunks = list(provider.complete_stream([{"role": "user", "content": "hi"}]))

    assert len(chunks) == 1 and not chunks[0].is_ok()
    assert VAR in chunks[0].error
    assert server.chat_requests == []


def test_a_set_variable_and_no_api_key_still_send(
    fake_model_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = fake_model_server(Scenario.from_dict({"turns": REPLY["turns"] * 2}))
    monkeypatch.setenv(VAR, "value-for-the-test")
    with_key = LocalHttpProvider(
        {"url": server.base_url, "model": "m", "api_key": f"${{{VAR}}}"}
    )
    assert with_key.complete([{"role": "user", "content": "hi"}]).is_ok()
    without = LocalHttpProvider({"url": server.base_url, "model": "m"})
    assert without.complete([{"role": "user", "content": "hi"}]).is_ok()
    assert len(server.chat_requests) == 2
