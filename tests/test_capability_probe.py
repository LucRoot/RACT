"""B-056: the capability probe behind ``ract doctor --check-providers``.

Most cases use an httpx mock transport so each server behavior is exact. The
two-provider case uses the fake model server and a closed port, so a failing
provider is shown next to a working one.
"""

from __future__ import annotations

import json
import socket
from typing import Any

import httpx
import pytest

from ract.providers.capability_probe import (
    CONTEXT_NEXT_STEP,
    TOOLS_FALLBACK,
    ProviderProbe,
    probe_configured,
    probe_provider,
)
from ract.providers.openai_provider import OpenAICompatibleProvider

URL = "http://127.0.0.1:9/v1"
MODEL = "probe-model"
KEY = "sk-SENTINEL-b056-7731"


def _sse(text: str) -> bytes:
    chunk = {"choices": [{"delta": {"content": text}, "finish_reason": None}]}
    return f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()


def _server(
    *,
    tools: str = "native",
    reasoning: bool = True,
    context: bool = True,
    chat: str = "normal",
    models_status: int = 200,
) -> tuple[Any, list[dict[str, Any]]]:
    """A handler plus the list of requests it saw, one dict per request."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            seen.append({"method": "GET", "path": request.url.path})
            if models_status != 200:
                return httpx.Response(models_status, json={"error": "no models"})
            entry: dict[str, Any] = {"id": MODEL, "object": "model"}
            if context:
                entry["context_length"] = 32768
            return httpx.Response(200, json={"object": "list", "data": [entry]})
        body = json.loads(request.content)
        seen.append({"method": "POST", "body": body})
        if chat == "down":
            raise httpx.ConnectError("refused", request=request)
        if chat == "html":
            return httpx.Response(200, text="<html>gateway says no</html>")
        if chat == "truncated":
            return httpx.Response(200, text='{"choices": [')
        if body.get("stream"):
            return httpx.Response(200, content=_sse("ok"), request=request)
        if "tools" in body:
            if tools == "reject":
                return httpx.Response(
                    400,
                    json={
                        "error": {"message": "tools are not supported by this model"}
                    },
                )
            if tools == "ignore":
                return httpx.Response(200, json=_reply("ok"))
            return httpx.Response(200, json=_tool_reply())
        return httpx.Response(200, json=_reply("ok", reasoning=reasoning))

    return handler, seen


def _reply(text: str, *, reasoning: bool = False) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if reasoning:
        message["reasoning_content"] = "Thinking about the word."
    return {"choices": [{"message": message, "finish_reason": "stop"}]}


def _tool_reply() -> dict[str, Any]:
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "echo", "arguments": json.dumps({"text": "hi"})},
    }
    return {"choices": [{"message": {"role": "assistant", "tool_calls": [call]}}]}


def _provider(handler: Any, key: str = KEY) -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider(
        {"url": URL, "model": MODEL, "api_key": key, "max_retries": 0}
    )
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    return provider


def _finding(probe: ProviderProbe, label: str) -> Any:
    return next(f for f in probe.findings if f.label == label)


def _probe(**server_options: Any) -> tuple[ProviderProbe, list[dict[str, Any]]]:
    handler, seen = _server(**server_options)
    probe = probe_provider("local", _provider(handler), url=URL, model=MODEL)
    return probe, seen


# ---------------------------------------------------------------- everything works


def test_a_server_with_everything_reports_every_fact() -> None:
    probe, seen = _probe()
    assert _finding(probe, "chat").status == "works"
    assert _finding(probe, "streaming").status == "works"
    assert _finding(probe, "tool calling").status == "works"
    assert _finding(probe, "reasoning text").status == "returned"
    context = _finding(probe, "context window")
    assert (
        context.status == "known" and context.detail == "32768 tokens, from the server"
    )
    assert probe.chat_works
    assert len(seen) == 4  # chat, stream, tools, models: no retries, no extra requests


def test_reasoning_is_not_returned_when_the_reply_has_none() -> None:
    probe, _ = _probe(reasoning=False)
    assert _finding(probe, "reasoning text").status == "not returned"


def test_context_size_is_unknown_when_the_server_does_not_say() -> None:
    probe, _ = _probe(context=False)
    context = _finding(probe, "context window")
    assert context.status == "unknown"
    assert context.next_step == CONTEXT_NEXT_STEP
    assert "context_budget_tokens" in context.next_step


def test_a_models_listing_that_fails_is_unknown_with_the_reason() -> None:
    probe, _ = _probe(models_status=404)
    context = _finding(probe, "context window")
    assert context.status == "unknown"
    assert context.detail.startswith("could not read /models: HTTP 404")


# ---------------------------------------------------------------- tool gaps


def test_a_server_that_rejects_tools_gets_the_fallback_sentence() -> None:
    probe, _ = _probe(tools="reject")
    tools = _finding(probe, "tool calling")
    assert tools.status == "not supported"
    assert tools.next_step == TOOLS_FALLBACK
    assert probe.chat_works  # a gap in tools is not a failed provider


def test_a_server_that_ignores_tools_answers_without_a_call() -> None:
    probe, _ = _probe(tools="ignore")
    tools = _finding(probe, "tool calling")
    assert tools.status == "not supported"
    assert tools.detail == "the server answered without a tool call"
    assert tools.next_step == TOOLS_FALLBACK


# ---------------------------------------------------------------- failures


def test_a_refused_connection_fails_chat_and_skips_the_rest() -> None:
    probe, seen = _probe(chat="down")
    chat = _finding(probe, "chat")
    assert chat.status == "failed"
    assert chat.detail == f"nothing is answering at {URL} (connection refused)"
    assert chat.next_step.startswith("start your model server")
    for label in ("streaming", "tool calling", "reasoning text", "context window"):
        assert _finding(probe, label).status == "not tried"
    assert not probe.chat_works
    assert [r["method"] for r in seen] == [
        "POST"
    ]  # the refused chat was the only attempt


@pytest.mark.parametrize("chat", ["html", "truncated"])
def test_a_garbage_answer_is_explained_in_plain_words(chat: str) -> None:
    probe, _ = _probe(chat=chat)
    chat_finding = _finding(probe, "chat")
    assert chat_finding.status == "failed"
    assert chat_finding.detail == "the server answered but not in the chat format"
    assert not probe.chat_works


def test_the_key_never_appears_in_the_report_even_when_echoed() -> None:
    def leaking(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": f"bad key {KEY}"})

    probe = probe_provider("local", _provider(leaking), url=URL, model=MODEL)
    text = json.dumps(probe.to_dict())
    assert KEY not in text
    assert KEY[3:20] not in text
    assert "********" in _finding(probe, "chat").detail


def test_the_key_is_not_in_the_report_for_a_working_server() -> None:
    probe, _ = _probe()
    assert KEY not in json.dumps(probe.to_dict())


# ---------------------------------------------------------------- configured providers


def test_an_unset_key_variable_is_named_and_no_request_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RACT_B056_UNSET_KEY", raising=False)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("no request may be sent for an unset key")

    monkeypatch.setattr(httpx.Client, "post", forbidden)
    monkeypatch.setattr(httpx.Client, "get", forbidden)
    probes = probe_configured(
        {
            "cloud": {
                "adapter": "openai_compatible",
                "url": "https://api.example.invalid/v1",
                "model": "m",
                "api_key": "${RACT_B056_UNSET_KEY}",
            }
        }
    )
    assert len(probes) == 1
    chat = _finding(probes[0], "chat")
    assert chat.status == "not tried"
    assert chat.detail == "the key variable RACT_B056_UNSET_KEY is not set"
    assert not probes[0].chat_works


def test_a_provider_with_no_url_is_not_contacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("no url means no request")

    monkeypatch.setattr(httpx.Client, "post", forbidden)
    monkeypatch.setattr(httpx.Client, "get", forbidden)
    probes = probe_configured({"local": {"adapter": "local_http", "model": "m"}})
    assert _finding(probes[0], "chat").detail == (
        "no url is set for this provider in ract.yaml"
    )
    assert not probes[0].chat_works


def test_a_non_http_adapter_is_not_probed() -> None:
    probes = probe_configured({"internal": {"adapter": "internal", "model": "m"}})
    assert not probes[0].probed
    assert not probes[0].chat_works


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_two_providers_are_both_reported_and_one_failure_hides_nothing(
    fake_model_server: Any,
) -> None:
    server = fake_model_server("j1_first_run")
    probes = probe_configured(
        {
            "good": {
                "adapter": "local_http",
                "url": server.base_url,
                "model": "fake-coder",
            },
            "bad": {
                "adapter": "local_http",
                "url": f"http://127.0.0.1:{_closed_port()}/v1",
                "model": "m",
            },
        }
    )
    by_name = {p.name: p for p in probes}
    assert set(by_name) == {"good", "bad"}
    assert by_name["good"].chat_works
    assert _finding(by_name["good"], "streaming").status == "works"
    bad_chat = _finding(by_name["bad"], "chat")
    assert bad_chat.detail.endswith("(connection refused)")
    assert not by_name["bad"].chat_works


def test_a_probe_leaves_the_retry_policy_as_it_found_it() -> None:
    handler, _ = _server()
    provider = _provider(handler)
    before = provider._retry_policy
    probe_provider("local", provider, url=URL, model=MODEL)
    assert provider._retry_policy is before


def test_every_probe_request_is_tagged_with_the_probe_purpose() -> None:
    from ract import egress_ledger

    purposes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        purposes.append(egress_ledger._purpose.get())
        return _server()[0](request)

    probe_provider("local", _provider(handler), url=URL, model=MODEL)
    assert purposes and set(purposes) == {"probe"}


def test_the_probe_report_is_plain_data_for_json_output() -> None:
    probe, _ = _probe()
    data = json.loads(json.dumps(probe.to_dict()))
    assert data["provider"] == "local"
    assert data["chat_works"] is True
    assert {f["label"] for f in data["findings"]} == {
        "chat",
        "streaming",
        "tool calling",
        "reasoning text",
        "context window",
    }


def test_base_url_is_read_when_url_is_not_set(fake_model_server: Any) -> None:
    server = fake_model_server("j1_first_run")
    probes = probe_configured(
        {
            "local": {
                "adapter": "local_http",
                "base_url": server.base_url,
                "model": "fake-coder",
            }
        }
    )
    assert probes[0].url == server.base_url
    assert _finding(probes[0], "chat").status == "works"


def test_a_repository_named_host_is_tagged_and_a_loopback_one_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RACT_B056_UNSET_KEY", raising=False)
    probes = probe_configured(
        {
            "remote": {
                "adapter": "openai_compatible",
                "url": "https://models.example.invalid/v1",
                "model": "m",
                "api_key": "${RACT_B056_UNSET_KEY}",
            },
            "local": {
                "adapter": "openai_compatible",
                "url": "http://127.0.0.1:9/v1",
                "model": "m",
                "api_key": "${RACT_B056_UNSET_KEY}",
            },
        }
    )
    by_name = {p.name: p for p in probes}
    assert by_name["remote"].repo_named is True
    assert by_name["local"].repo_named is False
    assert by_name["remote"].to_dict()["repo_named"] is True
