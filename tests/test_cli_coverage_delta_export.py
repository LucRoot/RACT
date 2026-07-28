"""Tests for the ract coverage delta-export CLI verb."""

from __future__ import annotations


import json
import subprocess
import sys


def test_cli_coverage_delta_export_shows_verdict(tmp_path):
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_covered": 90.0,
                    "covered_lines": 90,
                    "missing_lines": 10,
                    "total_lines": 100,
                }
            }
        ),
        encoding="utf-8",
    )
    after.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_covered": 92.0,
                    "covered_lines": 92,
                    "missing_lines": 8,
                    "total_lines": 100,
                }
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "coverage",
            "delta-export",
            "--before",
            str(before),
            "--after",
            str(after),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "earn" in result.stdout
