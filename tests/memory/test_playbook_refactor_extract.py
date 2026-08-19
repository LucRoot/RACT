"""End-to-end test for the refactor_extract playbook."""

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
            "request_type": "refactor",
            "scope_hints": {
                "mentioned_symbols": ["process_order"],
                "mentioned_files": [],
                "mentioned_directories": [],
                "keywords": ["extract", "helper"],
                "exclude_paths": [],
            },
            "success_criteria": ["extracted helper is called"],
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
                    "name": "process_order",
                    "file_path": "orders.py",
                    "kind": "function",
                    "rationale": "target of extract",
                }
            ],
            "call_neighborhood": [],
            "architectural_context": "single function under extract",
            "similar_prior_work": [],
            "risk_zones": [],
        }
    )


def _plan_response() -> str:
    return json.dumps(
        {
            "target_symbols": [
                {
                    "name": "process_order",
                    "file_path": "orders.py",
                    "kind": "function",
                    "action": "modify",
                }
            ],
            "load_manifest": [
                {"name": "process_order", "file_path": "orders.py", "kind": "function"},
            ],
            "invariants": [],
            "verification_criteria": [],
            "risk_assessment": {"level": "medium", "rationale": "boundary"},
            "iteration_bound": 1,
        }
    )


def _edit_response() -> str:
    return json.dumps(
        {
            "unified_diff": (
                "--- a/orders.py\n"
                "+++ b/orders.py\n"
                "@@ -1,3 +1,6 @@\n"
                "-def process_order(x):\n"
                "-    return x + 1\n"
                "+def _bump(value):\n"
                "+    return value + 1\n"
                "+def process_order(x):\n"
                "+    return _bump(x)\n"
            ),
            "hunks": [
                {
                    "file_path": "orders.py",
                    "start_line": 1,
                    "end_line": 3,
                    "summary": "extract _bump",
                }
            ],
        }
    )


def test_refactor_extract_end_to_end(tmp_path: Path) -> None:
    provider = MockProvider(
        responses_by_function={
            "intake": _intake_response(),
            "research": _research_response(),
            "plan": _plan_response(),
            "edit": _edit_response(),
        }
    )
    spec = load_playbook("refactor_extract")
    result = run_playbook(
        spec,
        "extract the value bump into a helper inside process_order",
        tmp_path,
        provider,
        IndexBundle(),
        intake_context=IntakeContext(repo_root=tmp_path),
    )
    # refactor_extract runs a single edit invocation.
    assert len(result.edits) == 1
    diff = result.edits[0].unified_diff
    assert "@@" in diff
    assert "_bump" in diff
