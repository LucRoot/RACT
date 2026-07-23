# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract report --last --format json --output CLI path."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_report_last_json_writes_output_file(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    report_dir = tmp_path / ".rootact"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "loop_report.json").write_text(
        json.dumps({"final_decision": "done", "summary": "ok"}), encoding="utf-8"
    )
    output = tmp_path / "report.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "report",
            "--last",
            "--format",
            "json",
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
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["final_decision"] == "done"


# RACT 0.1.2 - Trust and tooling
