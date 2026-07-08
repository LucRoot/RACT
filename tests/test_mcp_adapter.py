# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the MCP adapter skeleton."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from typing import Any
from unittest.mock import patch

from rootact.mcp_adapter import McpToolResult, StdioMcpClient
from rootact.rooted import Rooted


def test_stdio_client_parses_tool_list():
    client = StdioMcpClient(command="echo")
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"tools": [{"name": "read_file", "description": "Read a file"}]},
    }
    with patch(
        "rootact.mcp_adapter.subprocess.run",
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
        "rootact.mcp_adapter.subprocess.run",
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


from rootact.mcp_adapter import McpAdapter, McpToolRegistry


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


# RACT 0.1.0 - Initial Public Release
