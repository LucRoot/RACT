import tempfile
import os
import secrets

from ract.receipt import (
    Receipt,
    sign_receipt,
    verify_receipt,
    save_receipt,
    load_receipt,
)


def _generate_keypair():
    # Generate a random 32-byte key for HMAC-SHA256
    key = secrets.token_bytes(32)
    return key, key


def test_sign_and_verify():
    private_pem, public_pem = _generate_keypair()
    receipt = Receipt(
        run_id="run-1",
        plan_hash="plan-1",
        diff_hash="diff-1",
        test_results="pass",
        signer_id="user-1",
    )
    signed_receipt = sign_receipt(receipt, private_pem)
    assert signed_receipt.signature != ""
    assert verify_receipt(signed_receipt, public_pem)


def test_tampering_fails_verification():
    private_pem, public_pem = _generate_keypair()
    receipt = Receipt(
        run_id="run-1",
        plan_hash="plan-1",
        diff_hash="diff-1",
        test_results="pass",
        signer_id="user-1",
    )
    signed_receipt = sign_receipt(receipt, private_pem)
    assert verify_receipt(signed_receipt, public_pem)

    # Tamper with run_id
    signed_receipt.run_id = "tampered"
    assert not verify_receipt(signed_receipt, public_pem)


def test_save_and_load():
    private_pem, public_pem = _generate_keypair()
    receipt = Receipt(
        run_id="run-1",
        plan_hash="plan-1",
        diff_hash="diff-1",
        test_results="pass",
        signer_id="user-1",
    )
    signed_receipt = sign_receipt(receipt, private_pem)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "receipt.json")
        save_receipt(signed_receipt, path)
        loaded_receipt = load_receipt(path)
        assert loaded_receipt.run_id == signed_receipt.run_id
        assert loaded_receipt.plan_hash == signed_receipt.plan_hash
        assert loaded_receipt.diff_hash == signed_receipt.diff_hash
        assert loaded_receipt.test_results == signed_receipt.test_results
        assert loaded_receipt.signer_id == signed_receipt.signer_id
        assert loaded_receipt.signature == signed_receipt.signature
        assert verify_receipt(loaded_receipt, public_pem)
