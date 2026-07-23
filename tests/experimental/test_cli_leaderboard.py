# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract leaderboard CLI verb."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_leaderboard_json_and_html(tmp_path):
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    (receipts_dir / "a.json").write_text(
        json.dumps(
            {
                "model": "qwen",
                "plan": "refactor",
                "mutation_survival": 0.9,
                "test_pass_rate": 0.95,
                "diff_surgicality": 0.88,
            }
        ),
        encoding="utf-8",
    )
    (receipts_dir / "b.json").write_text(
        json.dumps(
            {
                "model": "bonsai",
                "plan": "fix",
                "mutation_survival": 0.85,
                "test_pass_rate": 0.92,
                "diff_surgicality": 0.9,
            }
        ),
        encoding="utf-8",
    )

    result_json = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "leaderboard",
            "--receipts-dir",
            str(receipts_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_json.returncode == 0, result_json.stderr
    data = json.loads(result_json.stdout)
    assert len(data) == 2
    assert any(r.get("model") == "qwen" for r in data)

    result_html = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "leaderboard",
            "--receipts-dir",
            str(receipts_dir),
            "--html",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_html.returncode == 0, result_html.stderr
    assert "<table>" in result_html.stdout
    assert "qwen" in result_html.stdout


# RACT 0.1.1 - Trust and tooling
