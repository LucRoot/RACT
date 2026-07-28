"""Tests for the ract report --last --format markdown CLI path."""

from __future__ import annotations


import json
import subprocess
import sys


def test_cli_report_last_markdown_writes_output_file(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    report_dir = tmp_path / ".ract"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "loop_report.json").write_text(
        json.dumps({"final_decision": "done", "summary": "ok"}), encoding="utf-8"
    )
    output = tmp_path / "report.md"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "report",
            "--last",
            "--format",
            "markdown",
            "--output",
            str(output),
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert output.is_file()
    text = output.read_text(encoding="utf-8")
    assert "# RACT Run Report" in text
    assert "done" in text
    assert "ok" in text


# RACT 0.1.2 - Trust and tooling
