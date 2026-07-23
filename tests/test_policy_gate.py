from ract.policy_gate import evaluate_policy


def test_policy_gate_modes():
    """Test pass, missing receipt, quality below floor, and knot absent modes."""

    # Base evidence
    base_evidence = {
        "receipts": [
            {"file": "a.py", "quality_score": 0.8, "signature": "abc123"},
            {"file": "b.py", "quality_score": 0.9, "signature": "def456"},
        ],
        "changed_files": ["a.py", "b.py"],
    }

    # Pass case
    policy_pass = {
        "min_quality_score": 0.7,
        "max_unreceipted_ratio": 0.2,
        "require_receipt_signature": True,
    }
    result_pass = evaluate_policy(policy_pass, base_evidence)
    assert result_pass["passed"] is True
    assert result_pass["failures"] == []

    # Fail: Quality below floor
    policy_low_quality = {
        "min_quality_score": 0.95,
        "max_unreceipted_ratio": 0.2,
        "require_receipt_signature": True,
    }
    result_low_quality = evaluate_policy(policy_low_quality, base_evidence)
    assert result_low_quality["passed"] is False
    assert any("quality score" in f for f in result_low_quality["failures"])

    # Fail: Missing receipt (unreceipted ratio)
    policy_missing_receipt = {
        "min_quality_score": 0.7,
        "max_unreceipted_ratio": 0.0,
        "require_receipt_signature": True,
    }
    evidence_missing_receipt = {
        "receipts": [{"file": "a.py", "quality_score": 0.8, "signature": "abc123"}],
        "changed_files": ["a.py", "b.py"],
    }
    result_missing_receipt = evaluate_policy(
        policy_missing_receipt, evidence_missing_receipt
    )
    assert result_missing_receipt["passed"] is False
    assert any("Unreceipted ratio" in f for f in result_missing_receipt["failures"])

    # Fail: Receipt signature absent
    policy_no_signature = {
        "min_quality_score": 0.7,
        "max_unreceipted_ratio": 0.2,
        "require_receipt_signature": True,
    }
    evidence_no_signature = {
        "receipts": [
            {"file": "a.py", "quality_score": 0.8},
            {"file": "b.py", "quality_score": 0.9},
        ],
        "changed_files": ["a.py", "b.py"],
    }
    result_no_signature = evaluate_policy(policy_no_signature, evidence_no_signature)
    assert result_no_signature["passed"] is False
    assert any(
        "Required receipt signature missing" in f
        for f in result_no_signature["failures"]
    )
