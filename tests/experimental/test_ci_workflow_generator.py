from ract.experimental.ci_workflow_generator import generate_policy_gate_workflow


def test_generate_policy_gate_workflow_contains_commands():
    yml = generate_policy_gate_workflow("ract.yaml", "receipts")
    assert "ract policy-gate" in yml
    assert "ract receipt-chain verify" in yml
