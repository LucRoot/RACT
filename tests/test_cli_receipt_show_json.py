"""Tests for the ract receipt show --json CLI output."""

from __future__ import annotations


import json
import subprocess
import sys


def test_cli_receipt_show_json_outputs_receipt_fields(tmp_path):
    receipt = {
        "run_id": "run-show",
        "plan_hash": "abc",
        "diff_hash": "def",
        "test_results": "pass",
        "signer_id": "test",
        "signature": "sig",
    }
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "receipt",
            "show",
            str(receipt_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["run_id"] == "run-show"
    assert data["plan_hash"] == "abc"


# RACT 0.1.2 - Trust and tooling
