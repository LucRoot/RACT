# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract receipt diff CLI verb."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def _receipt(run_id: str) -> dict[str, str]:
    return {
        "run_id": run_id,
        "plan_hash": "abc",
        "diff_hash": "def",
        "test_results": "pass",
        "signer_id": "test",
        "signature": "",
    }


def test_cli_receipt_diff_reports_differing_fields(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(_receipt("run-a")), encoding="utf-8")
    b.write_text(json.dumps(_receipt("run-b")), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "rootact.cli", "receipt", "diff", str(a), str(b)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "differences" in data
    assert "run_id" in data["differences"]


def test_cli_receipt_diff_empty_for_identical_receipts(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(_receipt("same")), encoding="utf-8")
    b.write_text(json.dumps(_receipt("same")), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "rootact.cli", "receipt", "diff", str(a), str(b)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["differences"] == []


# RACT 0.1.2 - Trust and tooling
