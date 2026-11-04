from __future__ import annotations


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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx
else:
    from ract.lazy_import import lazy_module

    httpx = lazy_module("httpx")  # B-087b: imported at first use, not at start

from ract import egress_ledger, egress_scan, redaction
from ract.rooted import Rooted


_CREDENTIAL_NAME = (
    "key",
    "token",
    "secret",
    "password",
    "passwd",
    "auth",
    "credential",
)


def _register_credentials(values: Any) -> None:
    """Register the credential-named entries of an MCP server's env or headers (B-202).

    Only names that say they hold a credential: registering every value
    would also mask ordinary long values such as a PATH.
    """
    if not isinstance(values, dict):
        return
    for name, value in values.items():
        if isinstance(value, str) and any(
            w in str(name).lower() for w in _CREDENTIAL_NAME
        ):
            redaction.register_known(value)
            if " " in value:  # "Bearer <token>": the token alone too
                redaction.register_known(value.split(" ", 1)[1])


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

    @staticmethod
    def _scanned(params: dict[str, Any], destination: str) -> dict[str, Any]:
        """Redact secret-shaped values from request params before they leave.

        LR:: Tool arguments are written by the model and can hold file
        contents; they went to the MCP server unscanned (B-044, the same
        rule as S-022 for provider payloads).
        """
        cleaned, redacted = egress_scan.scan_payload(params)
        egress_scan.notify(redacted, destination)
        return dict(cleaned)


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
            payload["params"] = self._scanned(params, f"MCP server {self.command!r}")
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
                # B-202: a server's stderr can print its own credentials.
                error=redaction.redact(proc.stderr.strip())
                or f"exit code {proc.returncode}",
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


class SseMcpClient(McpAdapter):
    """Connect to an MCP server over Server-Sent Events.

    This implementation targets the simple SSE variant where JSON-RPC requests
    are POSTed to a single URL and responses arrive as `data:` lines on the
    same stream. It does not yet implement the full MCP session-handshake
    pattern (GET /sse + POST /message); that is queued for a future pass.
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self._request_id = 0
        self._client: httpx.Client | None = None

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = egress_ledger.client("mcp", timeout=self.timeout)
        return self._client

    def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            self._client.close()

    def _rpc(
        self, method: str, params: dict[str, Any] | None = None
    ) -> Rooted[dict[str, Any]]:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params is not None:
            payload["params"] = self._scanned(params, f"MCP server {self.url!r}")
        request_headers = {"Content-Type": "application/json", **self.headers}
        try:
            with self.client.stream(
                "POST",
                self.url,
                headers=request_headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                last_result: dict[str, Any] | None = None
                for line in response.iter_lines():
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        data_str = line[len("data: ") :]
                        try:
                            message = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if "error" in message:
                            return Rooted(
                                value=None,
                                assumption="MCP method succeeds.",
                                confidence=0.0,
                                provenance=["mcp_adapter.sse"],
                                error=message["error"].get(
                                    "message", "unknown MCP error"
                                ),
                            )
                        if "result" in message:
                            last_result = message.get("result", {})
                return Rooted(
                    value=last_result or {},
                    assumption="MCP SSE stream returned a result.",
                    confidence=1.0 if last_result is not None else 0.0,
                    provenance=["mcp_adapter.sse"],
                )
        except (httpx.HTTPError, OSError) as exc:
            return Rooted(
                value=None,
                assumption="MCP SSE endpoint is reachable.",
                confidence=0.0,
                provenance=["mcp_adapter.sse"],
                # B-202: an httpx error names the URL, user name and token included.
                error=redaction.redact(str(exc)),
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
            assumption="MCP server exposes a tools/list method over SSE.",
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
    ``ract.yaml``. Each server exposes tools; the registry routes a
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
            # B-202: a credential configured for a server is masked wherever
            # it would be printed, as a provider's key is.
            _register_credentials(spec.get("env"))
            _register_credentials(spec.get("headers"))
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
            elif transport == "sse":
                registry.register(
                    name,
                    SseMcpClient(
                        url=spec["url"],
                        headers=spec.get("headers"),
                        timeout=float(spec.get("timeout", 60.0)),
                    ),
                )
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


def health_check(adapter: McpAdapter) -> dict[str, Any]:
    """Return a health summary for an MCP adapter.

    The result reports whether the adapter exposes at least one tool, the
    number of tools discovered, and an optional error message.
    """
    listed = adapter.list_tools()
    if not listed.is_ok():
        return {"ok": False, "tools": 0, "error": listed.error or "tool listing failed"}
    tools = listed.unwrap()
    if tools:
        return {"ok": True, "tools": len(tools), "error": None}
    return {"ok": False, "tools": 0, "error": "no tools configured"}


# RACT v0.6.0 - Interactive Session
