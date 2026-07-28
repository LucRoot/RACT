"""Tests for the ract whisper --json CLI output."""

from __future__ import annotations


import json
import subprocess
import sys


def test_cli_whisper_json_outputs_brief(tmp_path):
    script = tmp_path / "echo_brief.py"
    script.write_text(
        "import sys\n_ = sys.stdin.read()\nprint('Legacy Whisperer brief content.')\n",
        encoding="utf-8",
    )
    config = tmp_path / "ract.yaml"
    config.write_text(
        "project:\n"
        "  name: test\n"
        "manager_provider: echo\n"
        "providers:\n"
        "  echo:\n"
        "    adapter: internal\n"
        f"    command: [python, {script}]\n",
        encoding="utf-8",
    )
    src = tmp_path / "module.py"
    src.write_text("def foo():\n    pass\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "whisper",
            "--intent",
            "refactor module",
            "--json",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "brief" in data
    assert data["intent"] == "refactor module"


# RACT 0.1.2 - Trust and tooling
