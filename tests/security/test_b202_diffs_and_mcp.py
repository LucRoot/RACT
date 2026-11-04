"""B-202 (part 2): setup's diff and the MCP paths print no literal key.

``ract setup --reconfigure`` showed a diff of the existing ract.yaml with any
literal ``api_key`` value in it; the MCP SSE error was ``str(exc)`` (the URL
with its user name and token), a stdio server's stderr was returned raw, and
``ract mcp call`` printed errors and tool output raw. The key here is a
throwaway value.
"""

from __future__ import annotations

from pathlib import Path

from ract.setup import wizard

KEY = "sk-proj-" + "B202" * 8


def test_the_reconfigure_diff_masks_a_literal_key_and_keeps_references(
    tmp_path: Path,
) -> None:
    (tmp_path / "ract.yaml").write_text(
        f"providers:\n  local:\n    url: http://127.0.0.1:9/v1\n    api_key: {KEY}\n",
        encoding="utf-8",
    )
    config = {
        "providers": {
            "local": {"url": "http://127.0.0.1:9/v1", "api_key": "${OPENAI_API_KEY}"}
        }
    }
    _draft, diff = wizard.write_config(tmp_path, config, reconfigure=True)
    assert KEY not in diff
    assert "${OPENAI_API_KEY}" in diff


def test_the_mcp_sse_error_names_no_credentials() -> None:
    import httpx

    from ract.mcp_adapter import SseMcpClient

    class Refusing:
        is_closed = False

        def stream(self, *_a: object, **_k: object) -> None:
            raise httpx.ConnectError(
                f"cannot connect to https://svc:{KEY}@mcp.invalid/sse"
            )

        def close(self) -> None:
            pass

    client = SseMcpClient("https://mcp.invalid/sse")
    client._client = Refusing()  # type: ignore[assignment]
    result = client._rpc("tools/list")
    assert not result.is_ok() and KEY not in (result.error or "")


def test_mcp_credentials_from_config_are_registered() -> None:
    from ract import redaction
    from ract.mcp_adapter import McpToolRegistry

    token = "tok-b202-" + "Q" * 24
    path_value = "C:/Program Files/Some Tool/bin;C:/Windows/System32"
    try:
        McpToolRegistry.from_config(
            {
                "mcp_servers": {
                    "local": {
                        "command": "srv",
                        "env": {"API_TOKEN": token, "PATH": path_value},
                    },
                    "web": {
                        "transport": "sse",
                        "url": "https://mcp.invalid/sse",
                        "headers": {"Authorization": f"Bearer {token}x"},
                    },
                }
            }
        )
        assert token not in redaction.redact(f"the server said {token}")
        assert f"{token}x" not in redaction.redact(f"sent {token}x")
        assert path_value in redaction.redact(path_value)  # not a credential
    finally:
        redaction.clear_known()
