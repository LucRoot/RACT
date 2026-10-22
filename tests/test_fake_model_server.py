"""Tests for the scripted fake model server in ``tests/fixtures``.

Each reply kind and each fault has a test that shows the server produces it
byte for byte. The provider smoke tests at the bottom pin how today's
``OpenAICompatibleProvider`` and ``LocalHttpProvider`` read it, before the
agent loop changes them.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fixtures.fake_model_server import (
    FakeModelServer,
    Scenario,
    ScenarioError,
    iter_scenario_names,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _scenario(*replies: dict[str, Any], **settings: Any) -> Scenario:
    return Scenario.from_dict(
        {"name": "inline", **settings, "turns": [{"reply": r} for r in replies]}
    )


def _post(
    server: FakeModelServer, body: dict[str, Any] | None = None, **kw: Any
) -> httpx.Response:
    payload = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        **(body or {}),
    }
    return httpx.post(
        f"{server.base_url}/chat/completions",
        json=payload,
        timeout=kw.get("timeout", 10),
    )


def _stream_lines(
    server: FakeModelServer, body: dict[str, Any] | None = None
) -> list[str]:
    payload = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
        **(body or {}),
    }
    with httpx.stream(
        "POST", f"{server.base_url}/chat/completions", json=payload, timeout=10
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        return [line for line in resp.iter_lines() if line]


def _chunks(lines: list[str]) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :])
        for line in lines
        if line.startswith("data: {")
    ]


def _raw_stream(server: FakeModelServer) -> bytes:
    payload = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }
    with httpx.stream(
        "POST", f"{server.base_url}/chat/completions", json=payload, timeout=10
    ) as resp:
        return b"".join(resp.iter_raw())


# ---------------------------------------------------------------- basics


def test_binds_loopback_ephemeral_port_and_starts_fast() -> None:
    t0 = time.perf_counter()
    with FakeModelServer(_scenario({"kind": "text", "content": "x"})) as server:
        elapsed = time.perf_counter() - t0
        assert server.base_url.startswith("http://127.0.0.1:")
        assert server.port != 0
    assert elapsed < 0.2


def test_models_endpoint_and_unknown_route() -> None:
    with FakeModelServer(
        _scenario({"kind": "text", "content": "x"}, model="fake-x")
    ) as server:
        models = httpx.get(f"{server.base_url}/models", timeout=5).json()
        assert models["data"][0]["id"] == "fake-x"
        missing = httpx.get(f"{server.root_url}/v2/other", timeout=5)
        assert missing.status_code == 404
        assert missing.json()["error"]["type"] == "not_found"


def test_every_shipped_scenario_loads() -> None:
    names = list(iter_scenario_names())
    assert {
        "j1_first_run",
        "j1_no_tools",
        "j3_ask_code",
        "j4_fix_test",
        "j6_slow",
        "j9_weak_model",
        "j10_faults",
    } <= set(names)
    for name in names:
        Scenario.load(name)


def test_unknown_scenario_lists_available() -> None:
    with pytest.raises(ScenarioError, match="available: .*j3_ask_code"):
        Scenario.load("no_such_scenario")


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"turns": []}, "non-empty 'turns'"),
        ({"turns": [{"reply": {"kind": "poem"}}]}, "reply kind 'poem'"),
        (
            {"turns": [{"reply": {"kind": "fault", "fault": "meteor"}}]},
            "fault 'meteor'",
        ),
        (
            {
                "tools_supported": False,
                "turns": [{"reply": {"kind": "tool_calls", "calls": []}}],
            },
            "tools_supported=false",
        ),
    ],
)
def test_malformed_scenarios_name_the_problem(
    bad: dict[str, Any], message: str
) -> None:
    with pytest.raises(ScenarioError, match=message):
        Scenario.from_dict(bad)


# ---------------------------------------------------------------- reply kinds


def test_text_non_streaming() -> None:
    with FakeModelServer(
        _scenario({"kind": "text", "content": "hello there"})
    ) as server:
        data = _post(server).json()
    choice = data["choices"][0]
    assert choice["message"] == {"role": "assistant", "content": "hello there"}
    assert choice["finish_reason"] == "stop"
    assert data["id"] == "chatcmpl-fake-1"
    assert data["created"] == 1700000000


def test_text_streaming_chunk_boundaries_and_done() -> None:
    with FakeModelServer(
        _scenario({"kind": "text", "content": "abcdefghij", "chunk_size": 4})
    ) as server:
        lines = _stream_lines(server)
    assert lines[-1] == "data: [DONE]"
    deltas = [c["choices"][0]["delta"].get("content") for c in _chunks(lines)]
    assert deltas == ["", "abcd", "efgh", "ij", None]
    assert _chunks(lines)[-1]["choices"][0]["finish_reason"] == "stop"


def test_tool_calls_single_non_streaming() -> None:
    reply = {
        "kind": "tool_calls",
        "calls": [{"name": "read_file", "arguments": {"path": "a.py"}}],
    }
    with FakeModelServer(_scenario(reply)) as server:
        message = _post(server).json()["choices"][0]
    assert message["finish_reason"] == "tool_calls"
    call = message["message"]["tool_calls"][0]
    assert call == {
        "id": "call_1_0",
        "type": "function",
        "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
    }
    assert message["message"]["content"] is None


def test_tool_calls_parallel_with_text_and_fragmented_arguments() -> None:
    reply = {
        "kind": "tool_calls",
        "content": "Reading both.",
        "arg_fragment_size": 5,
        "calls": [
            {"name": "read_file", "arguments": {"path": "src/a.py"}},
            {"name": "grep", "arguments": {"pattern": "def x"}},
        ],
    }
    with FakeModelServer(_scenario(reply)) as server:
        chunks = _chunks(_stream_lines(server))
    text = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks)
    assert text == "Reading both."
    calls: dict[int, dict[str, str]] = {}
    fragments = 0
    for c in chunks:
        for tc in c["choices"][0]["delta"].get("tool_calls", []):
            entry = calls.setdefault(tc["index"], {"name": "", "arguments": ""})
            if "name" in tc.get("function", {}):
                entry["name"] = tc["function"]["name"]
            piece = tc.get("function", {}).get("arguments", "")
            if piece:
                fragments += 1
                assert len(piece) <= 5
            entry["arguments"] += piece
    assert calls[0] == {"name": "read_file", "arguments": '{"path":"src/a.py"}'}
    assert calls[1] == {"name": "grep", "arguments": '{"pattern":"def x"}'}
    assert fragments > 2
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"


def test_json_envelope_valid_and_malformed() -> None:
    scenario = _scenario(
        {
            "kind": "json_envelope",
            "envelope": {"tool": "read_file", "arguments": {"path": "x"}},
        },
        {"kind": "json_envelope", "raw": 'Sure! {"tool": "read_file"'},
    )
    with FakeModelServer(scenario) as server:
        first = _post(server).json()["choices"][0]["message"]["content"]
        second = _post(server).json()["choices"][0]["message"]["content"]
    assert json.loads(first) == {"tool": "read_file", "arguments": {"path": "x"}}
    with pytest.raises(json.JSONDecodeError):
        json.loads(second)


def test_reasoning_field_with_and_without_answer() -> None:
    scenario = _scenario(
        {"kind": "reasoning", "reasoning": "hidden thought", "content": "answer"},
        {"kind": "reasoning", "reasoning": "only thought", "content": ""},
    )
    with FakeModelServer(scenario) as server:
        with_answer = _post(server).json()["choices"][0]["message"]
        streamed = _chunks(_stream_lines(server))
    assert with_answer == {
        "role": "assistant",
        "content": "answer",
        "reasoning_content": "hidden thought",
    }
    reasoning = "".join(
        c["choices"][0]["delta"].get("reasoning_content", "") for c in streamed
    )
    content = "".join(c["choices"][0]["delta"].get("content") or "" for c in streamed)
    assert reasoning == "only thought"
    assert content == ""


def test_reasoning_inline_closed_and_unclosed() -> None:
    scenario = _scenario(
        {
            "kind": "reasoning",
            "style": "inline",
            "reasoning": "think",
            "content": "answer",
        },
        {
            "kind": "reasoning",
            "style": "inline",
            "reasoning": "cut off",
            "close_think": False,
        },
    )
    with FakeModelServer(scenario) as server:
        closed = _post(server).json()["choices"][0]["message"]
        unclosed = _post(server).json()["choices"][0]["message"]
    assert closed == {"role": "assistant", "content": "<think>think</think>answer"}
    assert unclosed["content"] == "<think>cut off"


def test_truncated_mid_reasoning_and_mid_answer() -> None:
    scenario = _scenario(
        {"kind": "truncated", "reasoning": "long thought", "content": ""},
        {"kind": "truncated", "content": "half an ans"},
    )
    with FakeModelServer(scenario) as server:
        mid_reasoning = _post(server).json()["choices"][0]
        mid_answer = _chunks(_stream_lines(server))
    assert mid_reasoning["finish_reason"] == "length"
    assert mid_reasoning["message"]["content"] == ""
    assert mid_answer[-1]["choices"][0]["finish_reason"] == "length"


def test_first_byte_delay_and_mid_stream_stall() -> None:
    scenario = _scenario(
        {"kind": "text", "content": "x", "first_byte_delay": 0.3},
        {
            "kind": "text",
            "content": "abcdef",
            "chunk_size": 2,
            "stall": {"after_chunk": 2, "seconds": 0.3},
        },
    )
    with FakeModelServer(scenario) as server:
        t0 = time.perf_counter()
        _post(server)
        assert time.perf_counter() - t0 >= 0.3
        payload = {"model": "m", "messages": [], "stream": True}
        stamps: list[float] = []
        with httpx.stream(
            "POST", f"{server.base_url}/chat/completions", json=payload, timeout=10
        ) as resp:
            for line in resp.iter_lines():
                if line:
                    stamps.append(time.perf_counter())
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert max(gaps) >= 0.25


def test_server_without_tool_support_ignores_tools_parameter() -> None:
    scenario = _scenario(
        {"kind": "text", "content": "plain answer"}, tools_supported=False
    )
    tools = [
        {
            "type": "function",
            "function": {"name": "echo", "parameters": {"type": "object"}},
        }
    ]
    with FakeModelServer(scenario) as server:
        message = _post(server, {"tools": tools}).json()["choices"][0]["message"]
        recorded = server.chat_requests[0].body
    assert "tool_calls" not in message
    assert message["content"] == "plain answer"
    assert recorded["tools"] == tools


def test_usage_block_on_and_off() -> None:
    with FakeModelServer(_scenario({"kind": "text", "content": "abcdefgh"})) as server:
        on = _post(server).json()
    off_scenario = Scenario.from_dict(
        {
            "usage": False,
            "turns": [
                {"reply": {"kind": "text", "content": "abcdefgh"}, "repeat": True}
            ],
        }
    )
    with FakeModelServer(off_scenario) as server:
        off = _post(server).json()
        streamed = _chunks(_stream_lines(server))
    assert set(on["usage"]) == {"prompt_tokens", "completion_tokens", "total_tokens"}
    assert on["usage"]["completion_tokens"] == 2
    assert "usage" not in off
    assert all("usage" not in c for c in streamed)


# ---------------------------------------------------------------- faults


def test_http_429_with_and_without_retry_after() -> None:
    scenario = _scenario(
        {"kind": "fault", "fault": "http_429", "retry_after": 3},
        {"kind": "fault", "fault": "http_429"},
    )
    with FakeModelServer(scenario) as server:
        first, second = _post(server), _post(server)
    assert first.status_code == 429 and first.headers["retry-after"] == "3"
    assert second.status_code == 429 and "retry-after" not in second.headers


@pytest.mark.parametrize("fault, code", [("http_500", 500), ("http_503", 503)])
def test_http_5xx(fault: str, code: int) -> None:
    with FakeModelServer(_scenario({"kind": "fault", "fault": fault})) as server:
        resp = _post(server)
    assert resp.status_code == code
    assert resp.json()["error"]["type"] == "server_error"


def _read_until_error(
    server: FakeModelServer,
) -> tuple[list[str], BaseException | None]:
    payload = {"model": "m", "messages": [], "stream": True}
    received: list[str] = []
    try:
        with httpx.stream(
            "POST", f"{server.base_url}/chat/completions", json=payload, timeout=5
        ) as resp:
            for line in resp.iter_lines():
                if line:
                    received.append(line)
    except httpx.HTTPError as exc:
        return received, exc
    return received, None


def test_reset_mid_stream() -> None:
    # Only what a reset guarantees: an error, no [DONE], and at most the lines
    # sent before it. How many arrive is up to the client's kernel.
    reply = {
        "kind": "fault",
        "fault": "reset_mid_stream",
        "after_chunks": 2,
        "content": "abcdefghijklmnop",
        "chunk_size": 2,
    }
    with FakeModelServer(_scenario(reply)) as server:
        received, error = _read_until_error(server)
    assert isinstance(error, httpx.HTTPError)
    assert "data: [DONE]" not in received
    assert 0 <= len(received) <= 2


def test_truncated_close_delivers_exact_lines_then_fails() -> None:
    reply = {
        "kind": "fault",
        "fault": "truncated_close",
        "after_chunks": 3,
        "content": "abcdefghijklmnop",
        "chunk_size": 2,
    }
    with FakeModelServer(_scenario(reply)) as server:
        received, error = _read_until_error(server)
    assert isinstance(error, httpx.HTTPError)
    assert len(received) == 3
    assert all(line.startswith("data: {") for line in received)


def test_never_respond_times_out_client_and_stops_cleanly() -> None:
    server = FakeModelServer(
        _scenario({"kind": "fault", "fault": "never_respond"})
    ).start()
    try:
        with pytest.raises(httpx.ReadTimeout):
            _post(server, timeout=0.5)
    finally:
        t0 = time.perf_counter()
        server.stop()
    assert time.perf_counter() - t0 < 2.0


def test_non_json_missing_choices_and_empty_message() -> None:
    scenario = _scenario(
        {"kind": "fault", "fault": "non_json"},
        {"kind": "fault", "fault": "missing_choices"},
        {"kind": "fault", "fault": "empty_message"},
    )
    with FakeModelServer(scenario) as server:
        non_json, missing, empty = _post(server), _post(server), _post(server)
    assert non_json.status_code == 200
    assert non_json.headers["content-type"] == "text/html"
    with pytest.raises(json.JSONDecodeError):
        non_json.json()
    assert "choices" not in missing.json()
    assert empty.json()["choices"][0]["message"]["content"] == ""


def test_scenario_exhausted_is_a_named_500() -> None:
    with FakeModelServer(_scenario({"kind": "text", "content": "once"})) as server:
        _post(server)
        resp = _post(server)
    assert resp.status_code == 500
    assert resp.json()["error"]["type"] == "scenario_exhausted"


# ---------------------------------------------------------------- quirks


def test_quirk_no_done_crlf_and_close_after() -> None:
    reply = {
        "kind": "text",
        "content": "abcd",
        "chunk_size": 2,
        "done": False,
        "crlf": True,
        "close_after": True,
    }
    with FakeModelServer(_scenario(reply)) as server:
        raw = _raw_stream(server)
    assert b"[DONE]" not in raw
    assert raw.count(b"\r\n\r\n") == 4  # role chunk, two content chunks, final chunk
    assert b"\n\n" not in raw.replace(b"\r\n", b"")


# ---------------------------------------------------------------- matching and recording


def test_match_by_regex_and_turn_number_and_repeat() -> None:
    scenario = Scenario.from_dict(
        {
            "turns": [
                {
                    "match": {"last_message": "(?i)probe"},
                    "reply": {"kind": "text", "content": "probe-reply"},
                },
                {"match": {"turn": 3}, "reply": {"kind": "text", "content": "third"}},
                {"reply": {"kind": "text", "content": "default"}, "repeat": True},
            ]
        }
    )

    def ask(server: FakeModelServer, text: str) -> str:
        body = {"messages": [{"role": "user", "content": text}]}
        return _post(server, body).json()["choices"][0]["message"]["content"]

    with FakeModelServer(scenario) as server:
        assert ask(server, "hello") == "default"
        assert ask(server, "please PROBE now") == "probe-reply"
        assert ask(server, "anything") == "third"
        assert ask(server, "again") == "default"
        assert [turn for _, turn in server.turns_served] == [3, 1, 2, 3]


def test_requests_are_recorded_without_authorization() -> None:
    with FakeModelServer(_scenario({"kind": "text", "content": "x"})) as server:
        httpx.post(
            f"{server.base_url}/chat/completions",
            json={
                "model": "m",
                "messages": [{"role": "user", "content": "secret-free"}],
            },
            headers={"Authorization": "Bearer sk-should-not-be-kept", "X-Trace": "1"},
            timeout=5,
        )
        recorded = server.requests
    assert len(recorded) == 1
    req = recorded[0]
    assert req.method == "POST" and req.path == "/v1/chat/completions"
    assert "authorization" not in req.headers
    assert req.headers["x-trace"] == "1"
    assert req.body["messages"][0]["content"] == "secret-free"
    assert "sk-should-not-be-kept" not in json.dumps([r.headers for r in recorded])


# ---------------------------------------------------------------- determinism


def test_same_scenario_gives_identical_bytes_across_runs() -> None:
    def run() -> tuple[bytes, bytes]:
        scenario = Scenario.load("j3_ask_code")
        for turn in scenario.turns:
            turn.reply.pop("chunk_delay", None)
        with FakeModelServer(scenario) as server:
            first = _raw_stream(server)
            second = httpx.post(
                f"{server.base_url}/chat/completions",
                json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
                timeout=5,
            ).content
        return first, second

    assert run() == run()


# ---------------------------------------------------------------- command line


def test_cli_lists_scenarios() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "tests.fixtures.fake_model_server", "--list"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0
    assert "j3_ask_code" in out.stdout


def test_cli_serves_until_stopped() -> None:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.fixtures.fake_model_server",
            "--scenario",
            "j1_first_run",
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        first = proc.stdout.readline()
        assert first.startswith("fake model server: http://127.0.0.1:")
        base_url = first.split()[3]
        models = httpx.get(f"{base_url}/models", timeout=5).json()
        assert models["data"][0]["id"] == "fake-coder"
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_nothing_under_src_imports_the_fake_server() -> None:
    hits = [
        path
        for path in (REPO_ROOT / "src").rglob("*.py")
        if "fake_model_server" in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert hits == []


# ---------------------------------------------------------------- provider smoke tests


@pytest.mark.parametrize("adapter", ["openai", "local_http"])
def test_provider_non_streaming_smoke(fake_model_server: Any, adapter: str) -> None:
    from ract.providers.local_http_provider import LocalHttpProvider
    from ract.providers.openai_provider import OpenAICompatibleProvider

    server = fake_model_server("j1_first_run")
    cls = LocalHttpProvider if adapter == "local_http" else OpenAICompatibleProvider
    provider = cls(
        {
            "url": server.base_url,
            "model": "fake-coder",
            "api_key": "sk-test-not-real",
            "max_retries": 0,
        }
    )
    try:
        assert provider.health_check()
        result = provider.complete([{"role": "user", "content": "hello"}])
    finally:
        provider.close()
    assert result.is_ok(), result.error
    assert result.unwrap()["choices"][0]["message"]["content"].startswith("Hello.")
    sent = server.chat_requests[0]
    assert sent.body["stream"] is False
    assert "authorization" not in sent.headers  # redacted by the recorder either way
    if adapter == "local_http":
        assert "max_tokens" not in sent.body  # uncapped by default (Phase 0)
    else:
        assert sent.body["max_tokens"] == 512


@pytest.mark.parametrize("adapter", ["openai", "local_http"])
def test_provider_streaming_smoke(fake_model_server: Any, adapter: str) -> None:
    from ract.providers.local_http_provider import LocalHttpProvider
    from ract.providers.openai_provider import OpenAICompatibleProvider

    server = fake_model_server("j1_first_run")
    cls = LocalHttpProvider if adapter == "local_http" else OpenAICompatibleProvider
    provider = cls({"url": server.base_url, "model": "fake-coder", "max_retries": 0})
    try:
        chunks = list(provider.complete_stream([{"role": "user", "content": "hello"}]))
    finally:
        provider.close()
    assert all(c.is_ok() for c in chunks)
    text = "".join(
        c.unwrap()["choices"][0]["delta"].get("content") or "" for c in chunks
    )
    assert text.startswith("Hello. I can read")
    assert server.chat_requests[0].body["stream"] is True


def test_provider_reports_missing_choices_today(fake_model_server: Any) -> None:
    """Pins today's behavior: a 200 without choices is a Rooted error."""
    from ract.providers.openai_provider import OpenAICompatibleProvider

    server = fake_model_server(
        Scenario.from_dict(
            {"turns": [{"reply": {"kind": "fault", "fault": "missing_choices"}}]}
        )
    )
    provider = OpenAICompatibleProvider({"url": server.base_url, "max_retries": 0})
    try:
        result = provider.complete([{"role": "user", "content": "x"}])
    finally:
        provider.close()
    assert not result.is_ok()
    assert result.error == "Response missing choices array."
