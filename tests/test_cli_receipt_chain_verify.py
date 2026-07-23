# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract receipt chain-verify CLI output."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import hashlib
import json
import subprocess
import sys


def _entry(receipt: dict, prev_hash: str) -> dict:
    payload = json.dumps(receipt, sort_keys=True) + prev_hash
    entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return {"receipt": receipt, "prev_hash": prev_hash, "entry_hash": entry_hash}


def test_cli_receipt_chain_verify_reports_valid_chain(tmp_path):
    chain = tmp_path / "chain.jsonl"
    first = _entry({"run_id": "a"}, "")
    second = _entry({"run_id": "b"}, first["entry_hash"])
    chain.write_text(
        "\n".join(json.dumps(e) for e in [first, second]), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "receipt",
            "chain-verify",
            str(chain),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["broken_at"] is None


def test_cli_receipt_chain_verify_reports_broken_chain(tmp_path):
    chain = tmp_path / "chain.jsonl"
    first = _entry({"run_id": "a"}, "")
    second = _entry({"run_id": "b"}, first["entry_hash"])
    second["entry_hash"] = "tampered"
    chain.write_text(
        "\n".join(json.dumps(e) for e in [first, second]), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "receipt",
            "chain-verify",
            str(chain),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["broken_at"] == 1


# RACT 0.1.2 - Trust and tooling
