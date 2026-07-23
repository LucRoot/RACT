import json

from ract.receipt_chain import append_receipt, verify_chain


def test_append_links_hashes(tmp_path):
    chain = tmp_path / "chain.jsonl"
    first = append_receipt({"id": 1}, str(chain))
    second = append_receipt({"id": 2}, str(chain))
    assert second["prev_hash"] == first["entry_hash"]


def test_verify_chain_on_missing_file(tmp_path):
    chain = tmp_path / "missing.jsonl"
    result = verify_chain(str(chain))
    assert result == {"ok": True, "broken_at": None}


def test_verify_chain_on_valid_file(tmp_path):
    chain = tmp_path / "chain.jsonl"
    append_receipt({"id": 1}, str(chain))
    result = verify_chain(str(chain))
    assert result["ok"] is True
    assert result["broken_at"] is None


def test_verify_chain_detects_tampering(tmp_path):
    chain = tmp_path / "chain.jsonl"
    append_receipt({"id": 1}, str(chain))
    text = chain.read_text(encoding="utf-8")
    entry = json.loads(text.strip().splitlines()[-1])
    entry["entry_hash"] = "0" * 64
    chain.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    result = verify_chain(str(chain))
    assert result["ok"] is False
    assert result["broken_at"] == 0
