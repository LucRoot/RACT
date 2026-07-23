# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract receipt chain-export CLI verb."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_receipt_chain_export_roundtrips(tmp_path):
    chain = tmp_path / "chain.jsonl"
    entries = [
        {"receipt": {"run_id": "a"}, "prev_hash": "", "entry_hash": "abc123"},
        {"receipt": {"run_id": "b"}, "prev_hash": "abc123", "entry_hash": "def456"},
    ]
    chain.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "ract.cli", "receipt", "chain-export", str(chain)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "abc123" in result.stdout
    assert "def456" in result.stdout
