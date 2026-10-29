"""B-094: the provider probe's advice for hosted endpoints, and a timeout is not a failure.

The memory estimate describes this machine. It is given for a local server only,
and never for a remote endpoint. A tool-calling request that gets no answer is
reported as unknown, not as failed, because the probe does not know why.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ract.doctor_advice import Memory, advise
from ract.providers import capability_probe
from ract.providers.openai_provider import OpenAICompatibleProvider
from tests.fixtures.fake_model_server import FakeModelServer, Scenario

LOW_MEMORY = Memory(total_gb=63.0, free_gb=9.0)


def _config(url: str) -> dict[str, Any]:
    return {"providers": {"main": {"url": url, "model": "model-550b"}}}


def _memory_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if "billion parameters" in line]


def test_a_remote_endpoint_gets_no_local_memory_advice() -> None:
    lines = advise(_config("https://hosted.example.invalid/v1"), LOW_MEMORY, [], [])
    assert _memory_lines(lines) == []


def test_a_local_server_still_gets_the_memory_advice() -> None:
    lines = advise(_config("http://127.0.0.1:8080/v1"), LOW_MEMORY, [], [])
    assert len(_memory_lines(lines)) == 1
    lines = advise(_config("http://localhost:8080/v1"), LOW_MEMORY, [], [])
    assert len(_memory_lines(lines)) == 1


def _handler_that_times_out_on_tools(request: httpx.Request) -> httpx.Response:
    if b'"tools"' in request.content:
        raise httpx.ReadTimeout("no answer", request=request)
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        request=request,
    )


def test_a_tool_call_timeout_is_unknown_and_not_failed() -> None:
    provider = OpenAICompatibleProvider(
        {
            "url": "http://probe.invalid/v1",
            "model": "m",
            "api_key": "k",
            "max_retries": 0,
        }
    )
    provider._client = httpx.Client(
        transport=httpx.MockTransport(_handler_that_times_out_on_tools)
    )
    probe = capability_probe.probe_provider(
        "main", provider, url="http://probe.invalid/v1", model="m"
    )
    finding = next(f for f in probe.findings if f.label == "tool calling")
    assert finding.status == "unknown"
    assert finding.detail == "no answer in 15 s"


@pytest.mark.parametrize("seconds", [0.5])
def test_a_fake_server_that_never_answers_a_tool_call_gives_unknown(
    monkeypatch: pytest.MonkeyPatch, seconds: float
) -> None:
    monkeypatch.setattr(capability_probe, "PROBE_TIMEOUT_S", seconds)
    scenario = Scenario.from_dict(
        {
            "turns": [
                {
                    "match": {"last_message": "(?i)echo tool"},
                    "reply": {
                        "kind": "fault",
                        "fault": "never_respond",
                        "hold_seconds": 600,
                    },
                },
                {"reply": {"kind": "text", "content": "ok"}, "repeat": True},
            ]
        }
    )
    with FakeModelServer(scenario) as server:
        provider = OpenAICompatibleProvider(
            {
                "url": server.base_url,
                "model": "fake-coder",
                "api_key": "k",
                "max_retries": 0,
            }
        )
        probe = capability_probe.probe_provider(
            "main", provider, url=server.base_url, model="fake-coder"
        )
    finding = next(f for f in probe.findings if f.label == "tool calling")
    assert finding.status == "unknown", finding
    assert "failed" not in finding.status
