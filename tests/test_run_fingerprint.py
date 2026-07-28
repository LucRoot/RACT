from ract.run_fingerprint import diff_fingerprints, fingerprint_run


def test_fingerprint_run_is_deterministic():
    receipt = {
        "intent": "fix bug",
        "plan_steps": ["step1", "step2"],
        "provider_model": "qwen",
        "artifact_hashes": ["abc", "def"],
    }
    assert fingerprint_run(receipt) == fingerprint_run(receipt)
    assert len(fingerprint_run(receipt)) == 64


def test_fingerprint_run_changes_when_receipt_changes():
    receipt_a = {
        "intent": "fix bug",
        "plan_steps": ["step1"],
        "provider_model": "qwen",
        "artifact_hashes": ["abc"],
    }
    receipt_b = dict(receipt_a)
    receipt_b["intent"] = "add feature"
    assert fingerprint_run(receipt_a) != fingerprint_run(receipt_b)


def test_diff_fingerprints_returns_differing_keys():
    a = {"intent": "fix", "model": "qwen"}
    b = {"intent": "add", "model": "qwen", "extra": "x"}
    diff = diff_fingerprints(a, b)
    assert "intent" in diff
    assert "extra" in diff
    assert "model" not in diff


def test_diff_fingerprints_returns_empty_for_identical():
    d = {"intent": "fix"}
    assert diff_fingerprints(d, d) == []


def test_diff_fingerprints_returns_keys_only_in_first():
    a = {"intent": "fix", "extra": "x"}
    b = {"intent": "fix"}
    diff = diff_fingerprints(a, b)
    assert "extra" in diff
    assert "intent" not in diff


# RACT 0.1.1 - Trust and Tooling
