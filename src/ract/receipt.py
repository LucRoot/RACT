import json
import hashlib
import base64
import hmac
from dataclasses import dataclass, asdict


@dataclass
class Receipt:
    run_id: str
    plan_hash: str
    diff_hash: str
    test_results: str
    signer_id: str
    signature: str = ""

    def canonical_json(self) -> str:
        data = {
            "run_id": self.run_id,
            "plan_hash": self.plan_hash,
            "diff_hash": self.diff_hash,
            "test_results": self.test_results,
            "signer_id": self.signer_id,
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":"))


def sign_receipt(receipt: Receipt, private_key_pem: bytes) -> Receipt:
    # In this repo, "private_key_pem" is a raw bytes key for HMAC-SHA256
    # as cryptography is not installed. We treat the bytes as the secret key.
    canonical = receipt.canonical_json().encode("utf-8")
    signature = hmac.new(private_key_pem, canonical, hashlib.sha256).digest()
    receipt.signature = base64.b64encode(signature).decode("utf-8")
    return receipt


def verify_receipt(receipt: Receipt, public_key_pem: bytes) -> bool:
    # In HMAC, the public key is the same as the private key (shared secret)
    canonical = receipt.canonical_json().encode("utf-8")
    signature = base64.b64decode(receipt.signature.encode("utf-8"))
    expected_signature = hmac.new(public_key_pem, canonical, hashlib.sha256).digest()
    return hmac.compare_digest(signature, expected_signature)


def save_receipt(receipt: Receipt, path: str) -> None:
    data = asdict(receipt)
    with open(path, "w") as f:
        json.dump(data, f, sort_keys=True)


def load_receipt(path: str) -> Receipt:
    with open(path, "r") as f:
        data = json.load(f)
    return Receipt(**data)
