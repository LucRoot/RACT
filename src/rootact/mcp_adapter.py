# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Model Context Protocol (MCP) adapter skeleton for RACT.

MCP lets RACT call external tools such as file-system servers, database
connectors, browsers, and documentation indexes. This module provides the
interface and a stdio-based client. Full SSE support and tool discovery are
left as extensions.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rootact.rooted import Rooted


@dataclass(frozen=True)
class McpToolResult:
    """Result of calling an MCP tool."""

    tool: str
    content: list[dict[str, Any]]
    is_error: bool = False


class McpAdapter:
    """Base class for MCP server adapters."""

    def list_tools(self) -> Rooted[list[dict[str, Any]]]:
        """Return the list of tools exposed by the server."""
        raise NotImplementedError

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Rooted[McpToolResult]:
        """Call a named tool with the given arguments."""
        raise NotImplementedError


class StdioMcpClient(McpAdapter):
    """Connect to an MCP server over stdio and issue JSON-RPC requests."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: Path | str | None = None,
    ) -> None:
        self.command = command
        self.args = args or []
        self.env = env
        self.cwd = Path(cwd) if cwd else None
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _rpc(
        self, method: str, params: dict[str, Any] | None = None
    ) -> Rooted[dict[str, Any]]:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        try:
            proc = subprocess.run(
                [self.command, *self.args],
                input=json.dumps(payload) + "\n",
                capture_output=True,
                text=True,
                env=self.env,
                cwd=self.cwd,
                timeout=60,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            return Rooted(
                value=None,
                assumption="MCP server process is reachable.",
                confidence=0.0,
                provenance=["mcp_adapter.stdio"],
                error=str(exc),
            )
        if proc.returncode != 0:
            return Rooted(
                value=None,
                assumption="MCP server process exits cleanly.",
                confidence=0.0,
                provenance=["mcp_adapter.stdio"],
                error=proc.stderr.strip() or f"exit code {proc.returncode}",
            )
        try:
            response = json.loads(proc.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as exc:
            return Rooted(
                value=None,
                assumption="MCP server returns valid JSON-RPC.",
                confidence=0.0,
                provenance=["mcp_adapter.stdio"],
                error=f"Failed to parse MCP response: {exc}",
            )
        if "error" in response:
            return Rooted(
                value=None,
                assumption="MCP method succeeds.",
                confidence=0.0,
                provenance=["mcp_adapter.stdio"],
                error=response["error"].get("message", "unknown MCP error"),
            )
        return Rooted(
            value=response.get("result", {}),
            assumption="MCP method succeeds.",
            confidence=1.0,
            provenance=["mcp_adapter.stdio"],
        )

    def list_tools(self) -> Rooted[list[dict[str, Any]]]:
        result = self._rpc("tools/list")
        if not result.is_ok():
            return Rooted(
                value=None,
                assumption=result.assumption,
                confidence=result.confidence,
                provenance=result.provenance,
                error=result.error,
            )
        tools = result.unwrap().get("tools", [])
        return Rooted(
            value=tools,
            assumption="MCP server exposes a tools/list method.",
            confidence=1.0,
            provenance=[*result.provenance, "mcp_adapter.list_tools"],
        )

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Rooted[McpToolResult]:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if not result.is_ok():
            return Rooted(
                value=None,
                assumption=result.assumption,
                confidence=result.confidence,
                provenance=result.provenance,
                error=result.error,
            )
        data = result.unwrap()
        return Rooted(
            value=McpToolResult(
                tool=name,
                content=data.get("content", []),
                is_error=bool(data.get("isError")),
            ),
            assumption="MCP tool call returns content.",
            confidence=1.0,
            provenance=[*result.provenance, "mcp_adapter.call_tool"],
        )


class McpToolRegistry:
    """Collect and dispatch calls across configured MCP servers.

    The registry loads adapters from the ``mcp_servers`` section of
    ``rootact.yaml``. Each server exposes tools; the registry routes a
    ``tool_call`` step to the right server by matching the tool name prefix.

    LR:: Tool names are qualified as ``server_name/tool_name`` so plans are
    explicit about which server owns the call. The registry is intentionally
    small: it lists, calls, and records errors. Complex tool orchestration
    belongs in the loop controller, not here.
    """

    def __init__(self) -> None:
        self._servers: dict[str, McpAdapter] = {}

    def register(self, name: str, adapter: McpAdapter) -> None:
        """Register an MCP server adapter under *name*."""
        self._servers[name] = adapter

    def has_servers(self) -> bool:
        """Return True if at least one MCP server is registered."""
        return bool(self._servers)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "McpToolRegistry":
        """Build a registry from the ``mcp_servers`` section of a config dict."""
        registry = cls()
        servers = config.get("mcp_servers", {})
        for name, spec in servers.items():
            if not isinstance(spec, dict):
                continue
            transport = spec.get("transport", "stdio")
            if transport == "stdio":
                registry.register(
                    name,
                    StdioMcpClient(
                        command=spec["command"],
                        args=spec.get("args", []),
                        env=spec.get("env"),
                        cwd=spec.get("cwd"),
                    ),
                )
            # SSE transport is left as a future extension.
        return registry

    def list_all_tools(self) -> Rooted[list[dict[str, Any]]]:
        """Return a unified list of tools from all servers, prefixed by server."""
        unified: list[dict[str, Any]] = []
        for server_name, adapter in self._servers.items():
            tools_rooted = adapter.list_tools()
            if not tools_rooted.is_ok():
                continue
            for tool in tools_rooted.unwrap():
                tool = dict(tool)
                tool_name = tool.get("name", "")
                tool["name"] = f"{server_name}/{tool_name}"
                unified.append(tool)
        return Rooted(
            value=unified,
            assumption="At least one configured MCP server is reachable.",
            confidence=1.0 if unified else 0.0,
            provenance=["mcp_tool_registry.list_all_tools"],
        )

    def call_tool(
        self, qualified_name: str, arguments: dict[str, Any]
    ) -> Rooted[McpToolResult]:
        """Call a tool by its qualified ``server_name/tool_name``."""
        if "/" not in qualified_name:
            return Rooted(
                value=None,
                assumption="Tool name is qualified as server_name/tool_name.",
                confidence=0.0,
                provenance=["mcp_tool_registry.call_tool"],
                error=f"Unqualified tool name: {qualified_name}",
            )
        server_name, tool_name = qualified_name.split("/", 1)
        adapter = self._servers.get(server_name)
        if adapter is None:
            return Rooted(
                value=None,
                assumption=f"MCP server '{server_name}' is configured.",
                confidence=0.0,
                provenance=["mcp_tool_registry.call_tool"],
                error=f"No MCP server registered as '{server_name}'",
            )
        return adapter.call_tool(tool_name, arguments)


# RACT 0.1.1 - Trust and tooling
