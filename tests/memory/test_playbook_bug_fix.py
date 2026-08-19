"""End-to-end test for the bug_fix playbook including the reproduce phase."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ract.memory.composition_runner import (
    UnconfirmedBugError,
    run_playbook,
)
from ract.memory.functions import IndexBundle, IntakeContext
from ract.memory.functions.testing import MockProvider
from ract.memory.playbooks import load_playbook


def _intake_response() -> str:
    return json.dumps(
        {
            "request_type": "bug_fix",
            "scope_hints": {
                "mentioned_symbols": ["compute"],
                "mentioned_files": [],
                "mentioned_directories": [],
                "keywords": ["off-by-one"],
                "exclude_paths": [],
            },
            "success_criteria": ["tests/test_compute.py::test_edge passes"],
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
                    "name": "compute",
                    "file_path": "compute.py",
                    "kind": "function",
                    "rationale": "reported failure site",
                }
            ],
            "call_neighborhood": [],
            "architectural_context": "one function bug.",
            "similar_prior_work": [],
            "risk_zones": [],
        }
    )


def _plan_response() -> str:
    return json.dumps(
        {
            "target_symbols": [
                {
                    "name": "compute",
                    "file_path": "compute.py",
                    "kind": "function",
                    "action": "modify",
                }
            ],
            "load_manifest": [
                {"name": "compute", "file_path": "compute.py", "kind": "function"},
            ],
            "invariants": [],
            "verification_criteria": [],
            "risk_assessment": {"level": "low", "rationale": "isolated"},
            "iteration_bound": 1,
        }
    )


def _edit_response() -> str:
    return json.dumps(
        {
            "unified_diff": (
                "--- a/compute.py\n"
                "+++ b/compute.py\n"
                "@@ -1,2 +1,2 @@\n"
                "-def compute(n): return n * 2\n"
                "+def compute(n): return n * 2 + 1\n"
            ),
            "hunks": [
                {
                    "file_path": "compute.py",
                    "start_line": 1,
                    "end_line": 2,
                    "summary": "off-by-one fix",
                }
            ],
        }
    )


def _canned_provider() -> MockProvider:
    return MockProvider(
        responses_by_function={
            "intake": _intake_response(),
            "research": _research_response(),
            "plan": _plan_response(),
            "edit": _edit_response(),
        }
    )


def test_bug_fix_happy_path_confirms_reproduction(tmp_path: Path) -> None:
    """A reproduce command that exits non-zero passes the reproduce phase."""
    provider = _canned_provider()
    spec = load_playbook("bug_fix")
    # Portable failing command: python -c 'raise SystemExit(1)'.
    fail_command = f'"{sys.executable}" -c "raise SystemExit(1)"'
    result = run_playbook(
        spec,
        "fix off-by-one in compute",
        tmp_path,
        provider,
        IndexBundle(),
        intake_context=IntakeContext(repo_root=tmp_path),
        reproduce_command=fail_command,
    )
    assert len(result.edits) == 1
    assert "compute" in result.edits[0].unified_diff
    reproduce_rec = next(r for r in result.phase_records if r.function == "reproduce")
    assert reproduce_rec.outcome == "ok"


def test_bug_fix_without_reproduction_raises_unconfirmed_bug(tmp_path: Path) -> None:
    """A reproduce command that exits zero refuses to proceed."""
    provider = _canned_provider()
    spec = load_playbook("bug_fix")
    passing_command = f'"{sys.executable}" -c "raise SystemExit(0)"'
    with pytest.raises(UnconfirmedBugError) as excinfo:
        run_playbook(
            spec,
            "fix off-by-one in compute",
            tmp_path,
            provider,
            IndexBundle(),
            intake_context=IntakeContext(repo_root=tmp_path),
            reproduce_command=passing_command,
        )
    assert "did not reproduce" in str(excinfo.value)


def test_bug_fix_no_command_no_criteria_raises(tmp_path: Path) -> None:
    """No reproduce_command AND no pytest-shaped success_criteria refuses."""
    provider = MockProvider(
        responses_by_function={
            "intake": json.dumps(
                {
                    "request_type": "bug_fix",
                    "scope_hints": {
                        "mentioned_symbols": ["compute"],
                        "mentioned_files": [],
                        "mentioned_directories": [],
                        "keywords": [],
                        "exclude_paths": [],
                    },
                    "success_criteria": ["make it work"],
                    "constraints": [],
                    "priority_markers": {},
                    "ambiguity_flags": [],
                }
            ),
            "research": _research_response(),
            "plan": _plan_response(),
            "edit": _edit_response(),
        }
    )
    spec = load_playbook("bug_fix")
    with pytest.raises(UnconfirmedBugError):
        run_playbook(
            spec,
            "fix compute",
            tmp_path,
            provider,
            IndexBundle(),
            intake_context=IntakeContext(repo_root=tmp_path),
        )
