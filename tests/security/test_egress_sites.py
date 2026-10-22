"""B-044: the outbound sites that sent content unscanned now scan it.

The inventory found three: MCP tool calls (model-written arguments, over
HTTP or to a local process), GitHub release notes and GitHub release
assets. Provider payloads, the internal provider and web search were
already scanned (S-022, tests/security/test_egress_scan.py).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest

from ract import egress_ledger, mcp_adapter
from ract.github_release import GitHubReleaseClient, GitHubReleaseError
from tests.security.test_egress_scan import SHAPES

KEY = SHAPES["AWS access key id"]


def test_mcp_http_tool_arguments_are_scanned(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sent: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"jsonrpc":"2.0","id":1,"result":{"content":[]}}\n\n',
        )

    client = mcp_adapter.SseMcpClient("https://mcp.example.invalid/rpc")
    client._client = egress_ledger.client("mcp", transport=httpx.MockTransport(handler))

    result = client.call_tool("search", {"text": f"why does {KEY} fail", "n": 3})

    assert result.is_ok(), result.error
    body = json.loads(sent[0])
    assert KEY not in sent[0].decode()
    assert body["params"]["name"] == "search" and body["params"]["arguments"]["n"] == 3
    assert "redacted secret-shaped values before sending to MCP server" in (
        capsys.readouterr().err
    )


def test_mcp_stdio_tool_arguments_are_scanned(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["input"] = kwargs["input"]
        out = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"content": []}})
        return subprocess.CompletedProcess(cmd, 0, stdout=out + "\n", stderr="")

    monkeypatch.setattr(mcp_adapter.subprocess, "run", run)
    client = mcp_adapter.StdioMcpClient("some-server")

    client.call_tool("write", {"content": f"token = {KEY}"})

    assert KEY not in seen["input"]
    assert json.loads(seen["input"])["params"]["name"] == "write"


def _github(monkeypatch: pytest.MonkeyPatch, sent: list[Any]) -> GitHubReleaseClient:
    def post(
        self: Any, url: str, json: Any = None, content: Any = None, **kw: Any
    ) -> Any:
        sent.append(json if json is not None else content)
        return httpx.Response(201, json={"id": 1}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", post)
    return GitHubReleaseClient("tok", "owner", "repo")


def test_release_notes_are_scanned(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[Any] = []
    gh = _github(monkeypatch, sent)

    gh.create_release("v1", f"v1 {KEY}", body=f"Fixed the leak of {KEY}.")

    assert KEY not in json.dumps(sent[0])
    assert sent[0]["tag_name"] == "v1"


def test_a_text_asset_with_a_secret_is_not_uploaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[Any] = []
    gh = _github(monkeypatch, sent)
    monkeypatch.setattr(
        gh,
        "_get_release",
        lambda rid: {"upload_url": "https://uploads.example.invalid/a"},
    )
    asset = tmp_path / "notes.txt"
    asset.write_text(f"aws_access_key_id = {KEY}\n", encoding="utf-8")

    with pytest.raises(GitHubReleaseError, match="not uploaded"):
        gh.upload_asset(1, str(asset))
    assert sent == []

    binary = tmp_path / "logo.png"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    gh.upload_asset(1, str(binary))
    assert sent == [binary.read_bytes()]
