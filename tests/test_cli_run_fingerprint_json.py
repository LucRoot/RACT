# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract run-fingerprint --json CLI output."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_run_fingerprint_json_outputs_fingerprint(tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "run_id": "run-json",
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
        [
            sys.executable,
            "-m",
            "ract.cli",
            "run-fingerprint",
            str(receipt),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "fingerprint" in data
    assert data["fingerprint"]


# RACT 0.1.2 - Trust and tooling
