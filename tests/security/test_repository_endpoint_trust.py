"""S-030: a cloned repository's ract.yaml must not choose where your requests go.

`trust.trust_items` covered hooks, MCP servers, provider commands, the test
gates and web retrieval, but not the model endpoint. A repository could name
any host as its provider, and RACT sent the user's request and the curated
project context there with no question. A provider URL that is not loopback
and not a host the operator chose (a preset, OPENAI_BASE_URL, RACT_KEY_HOSTS)
is now a trust item, and an untrusted run sends nothing to it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from ract import trust, turn_context
from ract.providers.local_http_provider import LocalHttpProvider
from ract.providers.openai_provider import OpenAICompatibleProvider

HOST = "repository-named-host.example"
MARKER = "SECRET-PROJECT-QUESTION"


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A private user state directory, here and for child processes."""
    home = tmp_path / "state"
    home.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home))
    for name in ("OPENAI_BASE_URL", "RACT_KEY_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    trust._DECIDED.clear()
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}


def _config(ws: Path, url: str, adapter: str = "openai_compatible") -> Path:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "ract.yaml").write_text(
        "project:\n  name: demo\n\nmanager_provider: remote\n\n"
        f"providers:\n  remote:\n    adapter: {adapter}\n"
        f"    url: {url}\n    model: fake-coder\n",
        encoding="utf-8",
    )
    return ws


def _network(ws: Path) -> list[trust.TrustItem]:
    return [i for i in trust.trust_items(ws) if i.kind == "network"]


def test_a_repository_named_host_is_a_trust_item(tmp_path: Path, state: Any) -> None:
    ws = _config(tmp_path / "ws", f"https://{HOST}/v1")
    items = _network(ws)
    assert [i.name for i in items] == ["provider remote"]
    assert HOST in items[0].detail
    assert "your requests" in items[0].detail
    assert not trust.is_trusted(ws)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/v1",
        "http://localhost:11434/v1",
        "http://[::1]:9000/v1",
        "https://api.openai.com/v1",
        "https://openrouter.ai/api/v1",
    ],
)
def test_loopback_and_preset_hosts_need_no_trust(
    tmp_path: Path, state: Any, url: str
) -> None:
    assert _network(_config(tmp_path / "ws", url)) == []


def test_hosts_the_operator_chose_need_no_trust(
    tmp_path: Path, state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _config(tmp_path / "ws", f"https://{HOST}/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", f"https://{HOST}/v1")
    assert _network(ws) == []
    monkeypatch.delenv("OPENAI_BASE_URL")
    monkeypatch.setenv("RACT_KEY_HOSTS", f"MY_KEY={HOST}")
    assert _network(ws) == []


def test_base_url_is_checked_like_url(tmp_path: Path, state: Any) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "ract.yaml").write_text(
        "providers:\n  remote:\n    adapter: openai\n"
        f"    base_url: https://{HOST}/v1\n",
        encoding="utf-8",
    )
    assert [i.name for i in _network(ws)] == ["provider remote"]


def _recording(provider: OpenAICompatibleProvider) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    return seen


MESSAGES = [{"role": "user", "content": f"where is the config loader? {MARKER}"}]


@pytest.mark.parametrize("cls", [OpenAICompatibleProvider, LocalHttpProvider])
def test_an_untrusted_run_sends_nothing_to_a_repository_named_host(
    state: Any, cls: type[OpenAICompatibleProvider]
) -> None:
    provider = cls({"url": f"https://{HOST}/v1", "model": "m"})
    seen = _recording(provider)
    with turn_context.repository_extensions_off():
        result = provider.complete(MESSAGES)
        chunks = list(provider.complete_stream(MESSAGES))
        healthy = provider.health_check()
    assert seen == [], "the request reached the repository-named host"
    assert result.value is None
    assert result.error and "not trusted" in result.error and HOST in result.error
    assert result.hint and "ract trust" in result.hint
    assert len(chunks) == 1 and chunks[0].error == result.error
    assert healthy is False


def test_a_trusted_run_still_reaches_its_host(state: Any) -> None:
    provider = OpenAICompatibleProvider({"url": f"https://{HOST}/v1", "model": "m"})
    seen = _recording(provider)
    result = provider.complete(MESSAGES)
    assert result.error is None
    assert len(seen) == 1 and MARKER in seen[0].content.decode("utf-8")


def test_an_untrusted_run_still_reaches_loopback(state: Any) -> None:
    provider = OpenAICompatibleProvider({"url": "http://127.0.0.1:9/v1", "model": "m"})
    seen = _recording(provider)
    with turn_context.repository_extensions_off():
        result = provider.complete(MESSAGES)
    assert result.error is None and len(seen) == 1


def _ract(
    ws: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", *args],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=env,
        stdin=subprocess.DEVNULL,
    )


@pytest.mark.parametrize(
    "args",
    [
        ["run", "--config", "ract.yaml", "--", f"explain the loader {MARKER}"],
        ["-p", f"explain the loader {MARKER}"],
    ],
    ids=["one-shot", "headless"],
)
def test_a_cloned_repository_cannot_send_your_request_to_its_host(
    tmp_path: Path, state: dict[str, str], args: list[str]
) -> None:
    host = "repository-named-host.invalid"
    ws = _config(tmp_path / "ws", f"http://{host}/v1")
    (ws / "app.py").write_text("def load():\n    return {}\n", encoding="utf-8")
    result = _ract(ws, state, *args)
    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    assert "not trusted" in out and host in out, out
    assert "ract trust" in out, out
    if args[0] == "-p":
        hints = [line for line in out.splitlines() if line.startswith("hint:")]
        assert hints and all("ract trust" in line for line in hints), out
