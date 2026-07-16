__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from rootact.policy_gate import evaluate_policy


def test_policy_gate_modes():
    """Test pass, missing receipt, quality below floor, and knot absent modes."""

    # Base evidence
    base_evidence = {
        "receipts": [
            {"file": "a.py", "quality_score": 0.8, "has_knot": True},
            {"file": "b.py", "quality_score": 0.9, "has_knot": True},
        ],
        "changed_files": ["a.py", "b.py"],
    }

    # Pass case
    policy_pass = {
        "min_quality_score": 0.7,
        "max_unreceipted_ratio": 0.2,
        "require_knot": True,
    }
    result_pass = evaluate_policy(policy_pass, base_evidence)
    assert result_pass["passed"] is True
    assert result_pass["failures"] == []

    # Fail: Quality below floor
    policy_low_quality = {
        "min_quality_score": 0.95,
        "max_unreceipted_ratio": 0.2,
        "require_knot": True,
    }
    result_low_quality = evaluate_policy(policy_low_quality, base_evidence)
    assert result_low_quality["passed"] is False
    assert any("quality score" in f for f in result_low_quality["failures"])

    # Fail: Missing receipt (unreceipted ratio)
    policy_missing_receipt = {
        "min_quality_score": 0.7,
        "max_unreceipted_ratio": 0.0,
        "require_knot": True,
    }
    evidence_missing_receipt = {
        "receipts": [{"file": "a.py", "quality_score": 0.8, "has_knot": True}],
        "changed_files": ["a.py", "b.py"],
    }
    result_missing_receipt = evaluate_policy(
        policy_missing_receipt, evidence_missing_receipt
    )
    assert result_missing_receipt["passed"] is False
    assert any("Unreceipted ratio" in f for f in result_missing_receipt["failures"])

    # Fail: Knot absent
    policy_no_knot = {
        "min_quality_score": 0.7,
        "max_unreceipted_ratio": 0.2,
        "require_knot": True,
    }
    evidence_no_knot = {
        "receipts": [
            {"file": "a.py", "quality_score": 0.8, "has_knot": False},
            {"file": "b.py", "quality_score": 0.9, "has_knot": False},
        ],
        "changed_files": ["a.py", "b.py"],
    }
    result_no_knot = evaluate_policy(policy_no_knot, evidence_no_knot)
    assert result_no_knot["passed"] is False
    assert any("Root Knot marker missing" in f for f in result_no_knot["failures"])
