__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import json

import pytest

from ract.mutation_merge_gate import load_policies, MergePolicy


def test_load_policies_round_trip(tmp_path):
    path = tmp_path / "policies.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "auth-coverage",
                    "description": "auth files need coverage delta",
                    "trigger_pattern": ".*auth.*",
                    "condition": "coverage_delta >= 5",
                    "threshold": 5.0,
                    "action": "block",
                }
            ]
        ),
        encoding="utf-8",
    )
    policies = load_policies(str(path))
    assert len(policies) == 1
    assert policies[0] == MergePolicy(
        id="auth-coverage",
        description="auth files need coverage delta",
        trigger_pattern=".*auth.*",
        condition="coverage_delta >= 5",
        threshold=5.0,
        action="block",
    )


def test_load_policies_rejects_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_policies(str(path))
