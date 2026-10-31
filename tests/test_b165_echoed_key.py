"""B-165: a server that echoes the key in its error body never gets the key printed.

MASON's wrong-key setup walk: the fake server's 401 body repeated the
Authorization header, and setup printed it in full inside ``failed: HTTP 401``.
The key here is a throwaway value; the server is on loopback.
"""

from __future__ import annotations

import http.server
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from ract.providers.openai_provider import OpenAICompatibleProvider
from ract.setup import wizard
from tests.setup.test_wizard import _git_init

THROWAWAY = "sk-throwaway-b165-" + "E" * 32


class _Echo(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server name
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = (
            '{"error": {"message": "Incorrect API key provided: '
            + (self.headers.get("Authorization") or "")
            + '"}}'
        ).encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture
def echo(monkeypatch) -> Iterator[str]:
    server = http.server.HTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host = f"127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("OPENAI_API_KEY", THROWAWAY)
    monkeypatch.setenv("RACT_KEY_HOSTS", f"OPENAI_API_KEY={host}")
    monkeypatch.setenv("RACT_NO_NETWORK", "1")
    try:
        yield f"http://{host}/v1"
    finally:
        server.shutdown()


def _provider(url: str) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider({"url": url, "max_retries": 0, "model": "m"})


def test_the_error_of_a_completion_holds_no_echoed_key(echo: str) -> None:
    provider = _provider(echo)
    assert provider.api_key == THROWAWAY  # paired, so the key was sent and echoed
    result = provider.complete([{"role": "user", "content": "hi"}], max_tokens=4)
    assert not result.is_ok()
    assert "HTTP 401" in (result.error or "")
    assert THROWAWAY not in (result.error or "")


def test_the_error_of_a_stream_holds_no_echoed_key(echo: str) -> None:
    provider = _provider(echo)
    errors = [
        chunk.error or ""
        for chunk in provider.complete_stream(
            [{"role": "user", "content": "hi"}], max_tokens=4
        )
        if not chunk.is_ok()
    ]
    assert errors and all(THROWAWAY not in e for e in errors)
    assert any("HTTP 401" in e for e in errors)


def test_setup_prints_no_echoed_key_and_writes_none(
    tmp_path: Path, monkeypatch, echo: str
) -> None:
    monkeypatch.setenv("RACT_PRESET_BASE_URL", f"openai={echo}")
    _git_init(tmp_path)
    said: list[str] = []
    asked: list[str] = []
    io = wizard.Io(
        ask=lambda prompt: asked.append(prompt) or "",
        say=lambda line: said.append(str(line)),
        detect=lambda extra: [],
        width=lambda: 10_000,
    )
    answers = wizard.Answers(provider="cloud", cloud_preset="openai")

    code = wizard.run(tmp_path, answers=answers, interactive=False, io=io)

    transcript = "\n".join(said + asked)
    assert code == wizard.EXIT_PROVIDER and "failed: HTTP 401" in transcript
    assert THROWAWAY not in transcript
    # ract.yaml is checked on its own, apart from the transcript.
    written = (tmp_path / "ract.yaml").read_text(encoding="utf-8")
    assert THROWAWAY not in written
    assert (
        yaml.safe_load(written)["providers"]["openai"]["api_key"] == "${OPENAI_API_KEY}"
    )
