import hashlib
import json
from pathlib import Path

from ract.canonical import dumps_jcs


def _hash(receipt: dict, prev_hash: str) -> str:
    # v0.5.1 module_03: RFC 8785 JCS canonical form for chain hashing.
    payload = dumps_jcs(receipt).decode("utf-8") + prev_hash
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def append_receipt(receipt: dict, chain_path: str) -> dict:
    path = Path(chain_path)
    prev_hash = ""
    if path.exists():
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        if lines:
            prev_hash = json.loads(lines[-1]).get("entry_hash", "")
    entry_hash = _hash(receipt, prev_hash)
    entry = {"receipt": receipt, "prev_hash": prev_hash, "entry_hash": entry_hash}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return {"prev_hash": prev_hash, "entry_hash": entry_hash}


def verify_chain(chain_path: str) -> dict:
    path = Path(chain_path)
    if not path.exists():
        return {"ok": True, "broken_at": None}
    prev_hash = ""
    for idx, line in enumerate(path.read_text(encoding="utf-8").strip().splitlines()):
        entry = json.loads(line)
        receipt = entry["receipt"]
        expected = _hash(receipt, prev_hash)
        if entry.get("prev_hash") != prev_hash or entry.get("entry_hash") != expected:
            return {"ok": False, "broken_at": idx}
        prev_hash = entry["entry_hash"]
    return {"ok": True, "broken_at": None}
