"""End-to-end test for the refactor_rename playbook."""

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
                "mentioned_symbols": ["User"],
                "mentioned_files": [],
                "mentioned_directories": [],
                "keywords": ["rename", "Account"],
                "exclude_paths": [],
            },
            "success_criteria": ["all callers use Account"],
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
                    "name": "User",
                    "file_path": "models.py",
                    "kind": "class",
                    "rationale": "target of rename",
                },
                {
                    "name": "User",
                    "file_path": "views.py",
                    "kind": "class",
                    "rationale": "caller",
                },
            ],
            "call_neighborhood": [],
            "architectural_context": "two module rename target.",
            "similar_prior_work": [],
            "risk_zones": [],
        }
    )


def _plan_response() -> str:
    return json.dumps(
        {
            "target_symbols": [
                {
                    "name": "User",
                    "file_path": "models.py",
                    "kind": "class",
                    "action": "rename",
                }
            ],
            "load_manifest": [
                {"name": "User", "file_path": "models.py", "kind": "class"},
                {
                    "name": "views_uses_User",
                    "file_path": "views.py",
                    "kind": "function",
                },
            ],
            "invariants": [],
            "verification_criteria": [],
            "risk_assessment": {"level": "low", "rationale": "two files"},
            "iteration_bound": 3,
        }
    )


def _edit_response(file_path: str) -> str:
    return json.dumps(
        {
            "unified_diff": (
                f"--- a/{file_path}\n"
                f"+++ b/{file_path}\n"
                "@@ -1 +1 @@\n"
                "-class User:\n"
                "+class Account:\n"
            ),
            "hunks": [
                {
                    "file_path": file_path,
                    "start_line": 1,
                    "end_line": 1,
                    "summary": "rename",
                }
            ],
        }
    )


def test_refactor_rename_end_to_end(tmp_path: Path) -> None:
    # Any edit call returns the same-shape diff; MockProvider only keys on
    # function name, not on which file the plan carved out.
    provider = MockProvider(
        responses_by_function={
            "intake": _intake_response(),
            "research": _research_response(),
            "plan": _plan_response(),
            "edit": _edit_response("models.py"),
        }
    )
    spec = load_playbook("refactor_rename")
    result = run_playbook(
        spec,
        "rename the User class to Account",
        tmp_path,
        provider,
        IndexBundle(),
        intake_context=IntakeContext(repo_root=tmp_path),
    )
    # One edit per grouped file in the load_manifest.
    assert len(result.edits) == 2
    for diff in result.edits:
        assert "@@" in diff.unified_diff


def test_refactor_rename_records_iterations(tmp_path: Path) -> None:
    provider = MockProvider(
        responses_by_function={
            "intake": _intake_response(),
            "research": _research_response(),
            "plan": _plan_response(),
            "edit": _edit_response("models.py"),
        }
    )
    spec = load_playbook("refactor_rename")
    result = run_playbook(
        spec,
        "rename the User class to Account",
        tmp_path,
        provider,
        IndexBundle(),
        intake_context=IntakeContext(repo_root=tmp_path),
    )
    edit_records = [r for r in result.phase_records if r.function == "edit"]
    assert len(edit_records) == 2
    for rec in edit_records:
        assert rec.outcome == "ok"
        assert any("iteration" in note for note in rec.notes)
