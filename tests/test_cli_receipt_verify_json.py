"""Tests for the ract receipt verify --json CLI output."""

from __future__ import annotations


import json
import subprocess
import sys

from ract.receipt import Receipt, sign_receipt


def _signed_receipt(tmp_path, key: bytes):
    receipt = Receipt(
        run_id="run-1",
        plan_hash="abc",
        diff_hash="def",
        test_results="pass",
        signer_id="test",
    )
    signed = sign_receipt(receipt, key)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(
        json.dumps(
            {
                "run_id": signed.run_id,
                "plan_hash": signed.plan_hash,
                "diff_hash": signed.diff_hash,
                "test_results": signed.test_results,
                "signer_id": signed.signer_id,
                "signature": signed.signature,
            }
        ),
        encoding="utf-8",
    )
    return receipt_path


def test_cli_receipt_verify_json_reports_valid(tmp_path):
    key = b"correct-key-bytes"
    receipt_path = _signed_receipt(tmp_path, key)
    key_path = tmp_path / "key.bin"
    key_path.write_bytes(key)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "receipt",
            "verify",
            str(receipt_path),
            "--pubkey",
            str(key_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["valid"] is True
    assert data["receipt"]["run_id"] == "run-1"


def test_cli_receipt_verify_json_reports_invalid(tmp_path):
    key = b"correct-key-bytes"
    receipt_path = _signed_receipt(tmp_path, key)
    wrong_key_path = tmp_path / "wrong.bin"
    wrong_key_path.write_bytes(b"wrong-key-bytes")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "receipt",
            "verify",
            str(receipt_path),
            "--pubkey",
            str(wrong_key_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["valid"] is False


# RACT 0.1.2 - Trust and tooling
