"""Tests for the ract retrieval search --json CLI output."""

from __future__ import annotations


import json
import subprocess
import sys


def test_cli_retrieval_search_json_finds_query_term(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "greeting.py").write_text(
        "def hello():\n    return 'greeting world'\n", encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "retrieval",
            "search",
            "greeting",
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
    assert any("greeting" in item.get("content", "") for item in data)


# RACT 0.1.2 - Trust and tooling
