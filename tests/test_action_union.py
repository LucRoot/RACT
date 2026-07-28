"""Tests for the closed Pydantic action union.

Module_04 (SUBSTRATE §5). The union is the point: any ``kind`` outside
the shipped discriminator set fails validation, and every legal ``kind``
round-trips through construction, JSON serialisation, and JSON
deserialisation.
"""

from __future__ import annotations

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from ract.core.actions import (
    ACTION_MEMBERS,
    Action,
    DeleteFileAction,
    EmitEventAction,
    LEGAL_ACTION_KINDS,
    PlannedStep,
    ProposePredicateAction,
    ReadFileAction,
    RequestHandshakeAction,
    RunTestsAction,
    SearchWorkspaceAction,
    WriteFileAction,
)


ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)


def _seed_action(cls: type) -> dict[str, object]:
    """Return a minimal-viable payload for the given action class."""
    if cls is WriteFileAction:
        return {
            "kind": "write_file",
            "path": "src/foo.py",
            "content": "print('hi')\n",
            "rationale": "assumption-42",
        }
    if cls is RunTestsAction:
        return {"kind": "run_tests", "selector": "tests/test_foo.py"}
    if cls is ReadFileAction:
        return {"kind": "read_file", "path": "src/foo.py"}
    if cls is SearchWorkspaceAction:
        return {"kind": "search_workspace", "query": "def compile"}
    if cls is ProposePredicateAction:
        return {
            "kind": "propose_predicate",
            "predicate_kind": "test",
            "invocation": {"type": "pytest", "selector": "tests/test_new.py"},
            "rationale": "new invariant found in module_04 fixtures",
        }
    if cls is DeleteFileAction:
        return {
            "kind": "delete_file",
            "path": "src/dead_module.py",
            "rationale": "dead-code auction retired this module",
        }
    if cls is RequestHandshakeAction:
        return {
            "kind": "request_handshake",
            "handshake_kind": "tier2_network",
            "payload": {"host": "pypi.org"},
        }
    if cls is EmitEventAction:
        return {
            "kind": "emit_event",
            "event_kind": "step.progress",
            "payload": {"iteration": 3},
        }
    raise AssertionError(f"unknown action class in test seed: {cls!r}")


def test_unknown_kind_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ACTION_ADAPTER.validate_python({"kind": "shell_exec", "cmd": "rm -rf /"})
    msg = str(excinfo.value)
    assert "shell_exec" in msg or "discriminator" in msg or "tag" in msg


def test_missing_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        ACTION_ADAPTER.validate_python({"path": "src/x.py", "content": "hi"})


@pytest.mark.parametrize(
    "path",
    [
        "../../etc/passwd",
        "..\\..\\Windows\\System32",
        "/etc/passwd",
        "\\Windows\\System32\\drivers\\hosts",
        "C:/Windows/System32/hosts",
        "src/foo/../../etc/passwd",
        "src\x00foo.py",
    ],
)
def test_write_file_path_traversal_rejected(path: str) -> None:
    with pytest.raises(ValidationError):
        WriteFileAction(
            path=path,
            content="",
            rationale="assumption-1",
        )


@pytest.mark.parametrize(
    "path",
    ["../etc", "/tmp/foo", "\x00absurd"],
)
def test_read_file_path_traversal_rejected(path: str) -> None:
    with pytest.raises(ValidationError):
        ReadFileAction(path=path)


@pytest.mark.parametrize(
    "path",
    ["../etc", "/tmp/foo"],
)
def test_delete_file_path_traversal_rejected(path: str) -> None:
    with pytest.raises(ValidationError):
        DeleteFileAction(path=path, rationale="oops")


def test_run_tests_timeout_upper_bound_enforced() -> None:
    with pytest.raises(ValidationError):
        RunTestsAction(selector="tests/", timeout_seconds=6001)


def test_extra_field_rejected_on_every_action() -> None:
    for cls in ACTION_MEMBERS:
        payload = _seed_action(cls)
        payload["surprise"] = "unmeant"
        with pytest.raises(ValidationError):
            ACTION_ADAPTER.validate_python(payload)


def test_planned_step_discriminator_round_trip() -> None:
    """Every legal kind round-trips through PlannedStep JSON."""
    for cls in ACTION_MEMBERS:
        seed = _seed_action(cls)
        step = PlannedStep(
            step_id=f"step-{cls.__name__}",
            action=seed,  # type: ignore[arg-type]
        )
        # dict -> json -> dict -> PlannedStep and compare
        as_json = step.model_dump_json()
        as_dict = json.loads(as_json)
        rebuilt = PlannedStep.model_validate(as_dict)
        assert rebuilt == step
        assert type(rebuilt.action) is cls


def test_all_kinds_covered() -> None:
    """LEGAL_ACTION_KINDS must exactly match ACTION_MEMBERS' kinds."""
    kinds_from_members = {
        m.model_fields["kind"].default for m in ACTION_MEMBERS
    }
    assert kinds_from_members == LEGAL_ACTION_KINDS


def test_planned_step_defaults() -> None:
    step = PlannedStep(
        step_id="s1",
        action=RunTestsAction(selector="tests/"),
    )
    assert step.depends_on == ()
    assert step.assumptions == ()
    assert step.postconditions == ()


def test_planned_step_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        PlannedStep.model_validate(
            {
                "step_id": "s1",
                "action": {"kind": "run_tests", "selector": "tests/"},
                "surprise": True,
            }
        )
