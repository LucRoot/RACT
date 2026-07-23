__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from rootact.experimental.ci_workflow_generator import generate_policy_gate_workflow

def test_generate_policy_gate_workflow_contains_commands():
    yml = generate_policy_gate_workflow('ract.yaml', 'receipts')
    assert 'ract policy-gate' in yml
    assert 'ract receipt-chain verify' in yml
