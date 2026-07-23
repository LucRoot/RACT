"""Tests for the ract run-fingerprint CLI verb."""

from __future__ import annotations


import json
import subprocess
import sys


def test_cli_run_fingerprint_prints_fingerprint(tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "intent": "refactor test harness",
                "plan_steps": [{"action": "edit", "expected_artifact": "x.py"}],
                "provider": "local",
                "model": "test-model",
                "provider_model": "local/test-model",
                "artifact_hashes": {"x.py": "abc"},
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "ract.cli", "run-fingerprint", str(receipt)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
