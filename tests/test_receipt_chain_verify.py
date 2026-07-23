import json

from ract.receipt_chain import append_receipt, verify_chain


def test_verify_chain_detects_tampering(tmp_path):
    chain = tmp_path / "chain.jsonl"
    append_receipt({"id": 1}, str(chain))
    append_receipt({"id": 2}, str(chain))
    assert verify_chain(str(chain)) == {"ok": True, "broken_at": None}
    lines = chain.read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(lines[0])
    entry["receipt"]["id"] = 99
    lines[0] = json.dumps(entry)
    chain.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = verify_chain(str(chain))
    assert result["ok"] is False
    assert result["broken_at"] == 0
