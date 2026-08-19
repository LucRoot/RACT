"""End-to-end test for the unit_test playbook."""

from __future__ import annotations

import json
from pathlib import Path

from ract.memory.composition_runner import run_playbook
from ract.memory.functions import IndexBundle, IntakeContext
from ract.memory.functions.testing import MockProvider
from ract.memory.playbooks import load_playbook


def _intake_response() -> str:
    return json.dumps(
        {
            "request_type": "unit_test",
            "scope_hints": {
                "mentioned_symbols": ["greet"],
                "mentioned_files": [],
                "mentioned_directories": [],
                "keywords": ["test"],
                "exclude_paths": [],
            },
            "success_criteria": ["greet returns hi"],
            "constraints": [],
            "priority_markers": {},
            "ambiguity_flags": [],
        }
    )


def _research_response() -> str:
    return json.dumps(
        {
            "relevant_symbols": [
                {
                    "name": "greet",
                    "file_path": "greet.py",
                    "kind": "function",
                    "rationale": "under-test",
                }
            ],
            "call_neighborhood": [],
            "architectural_context": "add coverage.",
            "similar_prior_work": [],
            "risk_zones": [],
        }
    )


def _plan_response() -> str:
    return json.dumps(
        {
            "target_symbols": [
                {
                    "name": "test_greet",
                    "file_path": "tests/test_greet.py",
                    "kind": "function",
                    "action": "add",
                }
            ],
            "load_manifest": [
                {"name": "greet", "file_path": "greet.py", "kind": "function"},
            ],
            "invariants": [],
            "verification_criteria": [],
            "risk_assessment": {"level": "low", "rationale": "new file"},
            "iteration_bound": 1,
        }
    )


def _edit_response() -> str:
    return json.dumps(
        {
            "unified_diff": (
                "--- /dev/null\n"
                "+++ b/tests/test_greet.py\n"
                "@@ -0,0 +1,3 @@\n"
                "+from greet import greet\n"
                "+def test_greet():\n"
                "+    assert greet() == 'hi'\n"
            ),
            "hunks": [
                {
                    "file_path": "tests/test_greet.py",
                    "start_line": 0,
                    "end_line": 3,
                    "summary": "add happy-path test",
                }
            ],
        }
    )


def test_unit_test_end_to_end(tmp_path: Path) -> None:
    provider = MockProvider(
        responses_by_function={
            "intake": _intake_response(),
            "research": _research_response(),
            "plan": _plan_response(),
            "edit": _edit_response(),
        }
    )
    spec = load_playbook("unit_test")
    result = run_playbook(
        spec,
        "write a unit test for greet",
        tmp_path,
        provider,
        IndexBundle(),
        intake_context=IntakeContext(repo_root=tmp_path),
    )
    assert len(result.edits) == 1
    assert "test_greet" in result.edits[0].unified_diff
