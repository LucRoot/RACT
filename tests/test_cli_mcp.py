# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the `ract mcp` CLI command."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from rootact.cli import _mcp_command


def test_mcp_list_no_config(tmp_path: Path, capsys):
    missing = tmp_path / "rootact.yaml"
    exit_code = _mcp_command(["list", "--config", str(missing)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "config not found" in captured.err


def test_mcp_list_empty_config(tmp_path: Path, capsys):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text(
        yaml.safe_dump({"project": {"name": "demo"}}), encoding="utf-8"
    )
    exit_code = _mcp_command(["list", "--config", str(config_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No MCP tools configured" in captured.out


def test_mcp_list_shows_tools(tmp_path: Path, capsys):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "project": {"name": "demo"},
                "mcp_servers": {
                    "fs": {
                        "transport": "stdio",
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    mock_registry = MagicMock()
    mock_tools = MagicMock()
    mock_tools.error = None
    mock_tools.value = [
        {"name": "fs/read_file", "description": "Read a file."},
        {"name": "fs/list_directory", "description": "List a directory."},
    ]
    mock_registry.list_all_tools.return_value = mock_tools

    with patch("rootact.cli.McpToolRegistry.from_config", return_value=mock_registry):
        exit_code = _mcp_command(["list", "--config", str(config_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "fs/read_file" in captured.out
    assert "fs/list_directory" in captured.out
    assert "Read a file." in captured.out


def test_mcp_list_registry_error(tmp_path: Path, capsys):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text(
        yaml.safe_dump({"project": {"name": "demo"}, "mcp_servers": {}}),
        encoding="utf-8",
    )

    mock_registry = MagicMock()
    mock_tools = MagicMock()
    mock_tools.error = "server unreachable"
    mock_registry.list_all_tools.return_value = mock_tools

    with patch("rootact.cli.McpToolRegistry.from_config", return_value=mock_registry):
        exit_code = _mcp_command(["list", "--config", str(config_path)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "server unreachable" in captured.err
