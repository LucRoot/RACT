__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from rootact.in_toto_attestation import build_statement

def test_build_statement_keys():
    stmt = build_statement({'name': 'test', 'created': '2026-01-01', 'subject': []})
    assert stmt['_type'] == 'https://in-toto.io/Statement/v0.1'
    assert 'subject' in stmt
    assert 'predicateType' in stmt
    assert 'predicate' in stmt
