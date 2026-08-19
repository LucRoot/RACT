"""Tests for :mod:`ract.memory.composition_runner` and the playbook loader."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from ract.memory.composition_runner import (
    IterationBoundExceededError,
    PhaseSpec,
    PlaybookSchemaError,
    PlaybookSpec,
    UnknownPlaybookError,
    parse_playbook_payload,
    run_playbook,
)
from ract.memory.functions import IndexBundle, IntakeContext
from ract.memory.functions.testing import MockProvider
from ract.memory.playbooks import list_playbooks, load_playbook
from ract.memory.session import SessionMemory


EXPECTED_PLAYBOOKS: list[str] = [
    "bug_fix",
    "refactor_extract",
    "refactor_rename",
    "unit_test",
]


def test_list_playbooks_returns_exact_four_names() -> None:
    assert list_playbooks() == EXPECTED_PLAYBOOKS


def test_load_playbook_unknown_raises() -> None:
    with pytest.raises(UnknownPlaybookError) as excinfo:
        load_playbook("nonexistent")
    message = str(excinfo.value)
    for expected in EXPECTED_PLAYBOOKS:
        assert expected in message


def test_load_playbook_empty_name_raises() -> None:
    with pytest.raises(UnknownPlaybookError):
        load_playbook("")


def test_load_playbook_schema_drift_raises(tmp_path: Path) -> None:
    """A YAML with an unknown top-level field surfaces via PlaybookSchemaError."""
    drift = tmp_path / "drift.yaml"
    drift.write_text(
        "name: drift\nversion: 1\ndescription: bad\nphases:\n"
        "  - name: intake\n    function: intake\n"
        "unexpected_field: yes\n",
        encoding="utf-8",
    )
    with pytest.raises(PlaybookSchemaError) as excinfo:
        # Route through load_playbook by redirecting the shipped-set
        # discovery: mock PLAYBOOKS_DIR + list_playbooks to point at tmp.
        with (
            mock.patch("ract.memory.playbooks.PLAYBOOKS_DIR", tmp_path),
            mock.patch("ract.memory.playbooks.list_playbooks", return_value=["drift"]),
        ):
            load_playbook("drift")
    assert "unexpected_field" in str(excinfo.value)


def test_load_playbook_missing_required_field_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: bad\nversion: 1\ndescription: no phases\n", encoding="utf-8")
    with pytest.raises(PlaybookSchemaError) as excinfo:
        with (
            mock.patch("ract.memory.playbooks.PLAYBOOKS_DIR", tmp_path),
            mock.patch("ract.memory.playbooks.list_playbooks", return_value=["bad"]),
        ):
            load_playbook("bad")
    assert "phases" in str(excinfo.value)


def test_phase_unknown_function_raises() -> None:
    payload = {
        "name": "x",
        "version": 1,
        "description": "y",
        "phases": [{"name": "intake", "function": "nonsense_verb"}],
    }
    with pytest.raises(PlaybookSchemaError) as excinfo:
        parse_playbook_payload(payload, source_label="<in-memory>")
    assert "nonsense_verb" in str(excinfo.value)


def test_phase_budget_override_type_check() -> None:
    payload = {
        "name": "x",
        "version": 1,
        "description": "y",
        "phases": [
            {
                "name": "edit",
                "function": "edit",
                "budget_override": {"input_target": "six thousand"},
            }
        ],
    }
    with pytest.raises(PlaybookSchemaError) as excinfo:
        parse_playbook_payload(payload, source_label="<in-memory>")
    assert "input_target" in str(excinfo.value)


def test_duplicate_phase_name_raises() -> None:
    payload = {
        "name": "x",
        "version": 1,
        "description": "y",
        "phases": [
            {"name": "step", "function": "intake"},
            {"name": "step", "function": "research"},
        ],
    }
    with pytest.raises(PlaybookSchemaError) as excinfo:
        parse_playbook_payload(payload, source_label="<in-memory>")
    assert "step" in str(excinfo.value)


@pytest.mark.parametrize("playbook_name", EXPECTED_PLAYBOOKS)
def test_every_shipped_playbook_loads(playbook_name: str) -> None:
    spec = load_playbook(playbook_name)
    assert isinstance(spec, PlaybookSpec)
    assert spec.name == playbook_name
    assert spec.version == 1
    assert spec.description
    assert spec.phases
    for phase in spec.phases:
        assert isinstance(phase, PhaseSpec)


def _canned_intake_ambiguous() -> str:
    return json.dumps(
        {
            "request_type": "other",
            "scope_hints": {
                "mentioned_symbols": ["greet"],
                "mentioned_files": [],
                "mentioned_directories": [],
                "keywords": [],
                "exclude_paths": [],
            },
            "success_criteria": [],
            "constraints": [],
            "priority_markers": {},
            "ambiguity_flags": ["target unclear"],
        }
    )


def _canned_intake_clean() -> str:
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
            "success_criteria": ["test_greet passes"],
            "constraints": [],
            "priority_markers": {},
            "ambiguity_flags": [],
        }
    )


def _canned_research() -> str:
    return json.dumps(
        {
            "relevant_symbols": [
                {
                    "name": "greet",
                    "file_path": "greet.py",
                    "kind": "function",
                    "rationale": "target",
                }
            ],
            "call_neighborhood": [],
            "architectural_context": "one-function module",
            "similar_prior_work": [],
            "risk_zones": [],
        }
    )


def _canned_plan(file_paths: list[str], iteration_bound: int = 3) -> str:
    manifest = [
        {"name": f"sym_{i}", "file_path": fp, "kind": "function"}
        for i, fp in enumerate(file_paths)
    ]
    return json.dumps(
        {
            "target_symbols": [
                {
                    "name": "greet",
                    "file_path": file_paths[0] if file_paths else "greet.py",
                    "kind": "function",
                    "action": "modify",
                }
            ],
            "load_manifest": manifest,
            "invariants": [],
            "verification_criteria": [],
            "risk_assessment": {"level": "low", "rationale": "tiny"},
            "iteration_bound": iteration_bound,
        }
    )


def _canned_edit(file_path: str = "greet.py") -> str:
    return json.dumps(
        {
            "unified_diff": (
                f"--- a/{file_path}\n+++ b/{file_path}\n@@ -1 +1 @@\n-old\n+new\n"
            ),
            "hunks": [
                {
                    "file_path": file_path,
                    "start_line": 1,
                    "end_line": 1,
                    "summary": "swap",
                }
            ],
        }
    )


def test_session_memory_threads_outputs(tmp_path: Path) -> None:
    """Every phase's output is persisted to SessionMemory in order."""
    provider = MockProvider(
        responses_by_function={
            "intake": _canned_intake_clean(),
            "research": _canned_research(),
            "plan": _canned_plan(["greet.py"]),
            "edit": _canned_edit(),
        }
    )
    session = SessionMemory(session_path=tmp_path / "session.json")
    spec = load_playbook("unit_test")
    result = run_playbook(
        spec,
        "add a unit test for greet",
        tmp_path,
        provider,
        IndexBundle(),
        session=session,
        intake_context=IntakeContext(repo_root=tmp_path),
    )
    assert session.work_order is result.work_order
    assert session.research_bundle is result.research
    assert session.change_plan is result.plan
    assert session.candidate_diff is result.edits[0]
    assert (tmp_path / "session.json").exists()


def test_ambiguity_flag_surfaces_in_phase_record(tmp_path: Path) -> None:
    provider = MockProvider(
        responses_by_function={
            "intake": _canned_intake_ambiguous(),
            "research": _canned_research(),
            "plan": _canned_plan(["greet.py"]),
            "edit": _canned_edit(),
        }
    )
    spec = load_playbook("unit_test")
    result = run_playbook(
        spec,
        "make it better",
        tmp_path,
        provider,
        IndexBundle(),
        intake_context=IntakeContext(repo_root=tmp_path),
    )
    intake_record = next(r for r in result.phase_records if r.function == "intake")
    assert any("ambiguity_flag" in note for note in intake_record.notes)


def test_iteration_bound_exceeded_raises(tmp_path: Path) -> None:
    """A plan whose manifest exceeds iteration_bound refuses the loop."""
    file_paths = [f"file_{i}.py" for i in range(5)]
    provider = MockProvider(
        responses_by_function={
            "intake": _canned_intake_clean(),
            "research": _canned_research(),
            "plan": _canned_plan(file_paths, iteration_bound=1),
            "edit": _canned_edit(),
        }
    )
    spec = load_playbook("refactor_rename")
    with pytest.raises(IterationBoundExceededError):
        run_playbook(
            spec,
            "rename greet across five files",
            tmp_path,
            provider,
            IndexBundle(),
            intake_context=IntakeContext(repo_root=tmp_path),
        )
