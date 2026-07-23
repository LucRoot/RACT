__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

def generate_policy_gate_workflow(policy_file: str, receipts_dir: str) -> str:
    return f'''name: RACT Policy Gate
on: [push, pull_request]
jobs:
  ract-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {{python-version: "3.11"}}
      - run: pip install -e .
      - run: ract policy-gate --config {{{policy_file}}}
      - run: ract receipt-chain verify --receipts-dir {{{receipts_dir}}}
'''
