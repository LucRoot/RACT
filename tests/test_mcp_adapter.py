# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the MCP adapter skeleton."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from typing import Any
from unittest.mock import patch

import httpx

from ract.mcp_adapter import (
    McpToolResult,
    SseMcpClient,
    StdioMcpClient,
    health_check,
)
from ract.rooted import Rooted


def test_stdio_client_parses_tool_list():
    client = StdioMcpClient(command="echo")
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"tools": [{"name": "read_file", "description": "Read a file"}]},
    }
    with patch(
        "ract.mcp_adapter.subprocess.run",
        return_value=__import__("subprocess").CompletedProcess(
            args=["echo"],
            returncode=0,
            stdout=json.dumps(response) + "\n",
            stderr="",
        ),
    ):
        result = client.list_tools()
    assert result.is_ok()
    tools = result.unwrap()
    assert len(tools) == 1
    assert tools[0]["name"] == "read_file"


def test_stdio_client_propagates_error():
    client = StdioMcpClient(command="missing_command_xyz")
    result = client.list_tools()
    assert not result.is_ok()


def test_stdio_client_parses_tool_call():
    client = StdioMcpClient(command="echo")
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": "hello"}]},
    }
    with patch(
        "ract.mcp_adapter.subprocess.run",
        return_value=__import__("subprocess").CompletedProcess(
            args=["echo"],
            returncode=0,
            stdout=json.dumps(response) + "\n",
            stderr="",
        ),
    ):
        result = client.call_tool("read_file", {"path": "foo.txt"})
    assert result.is_ok()
    tool_result = result.unwrap()
    assert isinstance(tool_result, McpToolResult)
    assert tool_result.tool == "read_file"


from ract.mcp_adapter import McpAdapter, McpToolRegistry


class FakeMcpAdapter(McpAdapter):
    """In-memory MCP adapter for registry tests."""

    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self._tools = tools
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_tools(self) -> Rooted[list[dict[str, Any]]]:
        return Rooted(
            value=list(self._tools),
            assumption="fake adapter has tools",
            confidence=1.0,
            provenance=["fake_mcp_adapter.list_tools"],
        )

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Rooted[McpToolResult]:
        self.calls.append((name, arguments))
        return Rooted(
            value=McpToolResult(tool=name, content=[{"type": "text", "text": "ok"}]),
            assumption="fake tool succeeds",
            confidence=1.0,
            provenance=["fake_mcp_adapter.call_tool"],
        )


def test_registry_lists_tools_with_server_prefix():
    registry = McpToolRegistry()
    registry.register(
        "fs", FakeMcpAdapter([{"name": "read", "description": "read file"}])
    )
    registry.register(
        "db", FakeMcpAdapter([{"name": "query", "description": "run sql"}])
    )
    result = registry.list_all_tools()
    assert result.is_ok()
    tools = result.unwrap()
    names = {t["name"] for t in tools}
    assert names == {"fs/read", "db/query"}


def test_registry_routes_call_by_qualified_name():
    fs = FakeMcpAdapter([{"name": "read", "description": "read file"}])
    registry = McpToolRegistry()
    registry.register("fs", fs)
    result = registry.call_tool("fs/read", {"path": "x.txt"})
    assert result.is_ok()
    assert fs.calls == [("read", {"path": "x.txt"})]


def test_registry_rejects_unqualified_tool_name():
    registry = McpToolRegistry()
    result = registry.call_tool("read", {})
    assert not result.is_ok()


def test_registry_rejects_unknown_server():
    registry = McpToolRegistry()
    result = registry.call_tool("fs/read", {})
    assert not result.is_ok()


def test_registry_from_config_builds_stdio_clients():
    config = {
        "mcp_servers": {
            "fs": {
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem"],
            }
        }
    }
    registry = McpToolRegistry.from_config(config)
    assert "fs" in registry._servers
    assert isinstance(registry._servers["fs"], StdioMcpClient)


class _FakeSseStream:
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


def _sse_result(result: dict[str, Any]) -> str:
    return f"data: {json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': result})}"


def test_sse_client_list_tools():
    client = SseMcpClient("http://localhost:8080/sse")
    stream = _FakeSseStream(
        [_sse_result({"tools": [{"name": "read", "description": "x"}]})]
    )
    with patch.object(client.client, "stream", return_value=stream):
        result = client.list_tools()
    assert result.is_ok()
    assert result.unwrap() == [{"name": "read", "description": "x"}]


def test_sse_client_call_tool():
    client = SseMcpClient("http://localhost:8080/sse")
    stream = _FakeSseStream(
        [_sse_result({"content": [{"type": "text", "text": "ok"}], "isError": False})]
    )
    with patch.object(client.client, "stream", return_value=stream):
        result = client.call_tool("read", {"path": "x.txt"})
    assert result.is_ok()
    tool_result = result.unwrap()
    assert tool_result.tool == "read"
    assert tool_result.content == [{"type": "text", "text": "ok"}]


def test_sse_client_propagates_rpc_error():
    client = SseMcpClient("http://localhost:8080/sse")
    stream = _FakeSseStream(
        [
            f"data: {json.dumps({'jsonrpc': '2.0', 'id': 1, 'error': {'message': 'boom'}})}"
        ]
    )
    with patch.object(client.client, "stream", return_value=stream):
        result = client.list_tools()
    assert not result.is_ok()
    assert "boom" in (result.error or "")


def test_sse_client_http_error():
    client = SseMcpClient("http://localhost:8080/sse")

    def raise_on_stream(*_args, **_kwargs):
        raise httpx.ConnectError("down")

    with patch.object(client.client, "stream", side_effect=raise_on_stream):
        result = client.list_tools()
    assert not result.is_ok()
    assert "down" in (result.error or "")


def test_registry_from_config_builds_sse_clients():
    config = {
        "mcp_servers": {
            "memory": {
                "transport": "sse",
                "url": "http://localhost:8081/sse",
                "headers": {"Authorization": "Bearer token"},
            }
        }
    }
    registry = McpToolRegistry.from_config(config)
    assert "memory" in registry._servers
    assert isinstance(registry._servers["memory"], SseMcpClient)


class _FakeAdapter(McpAdapter):
    def __init__(
        self, tools: list[dict[str, Any]] | None = None, fail: bool = False
    ) -> None:
        self._tools = tools or []
        self._fail = fail

    def list_tools(self) -> Rooted[list[dict[str, Any]]]:
        if self._fail:
            return Rooted(
                value=None, error="listing failed", confidence=0.0, provenance=["fake"]
            )
        return Rooted(value=list(self._tools), confidence=1.0, provenance=["fake"])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Rooted[McpToolResult]:
        raise NotImplementedError


def test_health_check_ok_with_tools():
    adapter = _FakeAdapter([{"name": "read"}, {"name": "write"}])
    result = health_check(adapter)
    assert result == {"ok": True, "tools": 2, "error": None}


def test_health_check_fails_when_no_tools():
    adapter = _FakeAdapter([])
    result = health_check(adapter)
    assert result == {"ok": False, "tools": 0, "error": "no tools configured"}


def test_health_check_fails_when_listing_errors():
    adapter = _FakeAdapter(fail=True)
    result = health_check(adapter)
    assert result["ok"] is False
    assert result["tools"] == 0
    assert "listing failed" in (result["error"] or "")


# RACT 0.1.1 - Trust and Tooling
