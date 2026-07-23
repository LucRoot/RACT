"""Tests for the ract mcp list --json CLI output."""

from __future__ import annotations


import json
import subprocess
import sys


def test_cli_mcp_list_json_empty_config(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "mcp",
            "list",
            "--json",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data, list)


# RACT 0.1.2 - Trust and tooling
