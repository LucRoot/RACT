"""Tests for the ract leaderboard --json CLI output."""

from __future__ import annotations


import json
import subprocess
import sys


def test_cli_leaderboard_json_explicit_and_overrides_html(tmp_path):
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    (receipts_dir / "a.json").write_text(
        json.dumps(
            {
                "run_id": "run-a",
                "model": "qwen",
                "plan": "refactor",
                "mutation_survival": 0.9,
                "test_pass_rate": 0.95,
                "diff_surgicality": 0.88,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "leaderboard",
            "--receipts-dir",
            str(receipts_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert any(r.get("run_id") == "run-a" for r in data)

    result_html_override = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "leaderboard",
            "--receipts-dir",
            str(receipts_dir),
            "--json",
            "--html",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_html_override.returncode == 0, result_html_override.stderr
    data2 = json.loads(result_html_override.stdout)
    assert any(r.get("run_id") == "run-a" for r in data2)


# RACT 0.1.2 - Trust and tooling
