from typing import Dict, List, Any


def evaluate_policy(policy: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate CI policy against evidence. Returns pass/fail status and list of failures."""
    failures: List[str] = []

    # Check min_quality_score
    min_quality = policy.get("min_quality_score")
    if min_quality is not None:
        receipts = evidence.get("receipts", [])
        if not receipts:
            failures.append("No receipts provided")
        else:
            scores = [r.get("quality_score", 0.0) for r in receipts]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            if avg_score < min_quality:
                failures.append(
                    f"Average quality score {avg_score:.2f} below threshold {min_quality}"
                )

    # Check max_unreceipted_ratio
    max_ratio = policy.get("max_unreceipted_ratio")
    if max_ratio is not None:
        changed_files = evidence.get("changed_files", [])
        receipts = evidence.get("receipts", [])
        if not changed_files:
            pass  # No files changed, nothing to check
        else:
            receipt_files = {r.get("file", "") for r in receipts if r.get("file")}
            unreceipted = [f for f in changed_files if f not in receipt_files]
            ratio = len(unreceipted) / len(changed_files)
            if ratio > max_ratio:
                failures.append(
                    f"Unreceipted ratio {ratio:.2f} exceeds threshold {max_ratio}"
                )

    # Check require_receipt_signature
    if policy.get("require_receipt_signature", False):
        receipts = evidence.get("receipts", [])
        has_signature = any(r.get("signature", False) for r in receipts)
        if not has_signature:
            failures.append("Required receipt signature missing")

    return {"passed": len(failures) == 0, "failures": failures}
