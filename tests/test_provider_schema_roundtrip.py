"""Round-trip tests for the three provider schema converters.

Each converter emits a schema; a fake response for each action kind
validates through the schema; the parsed ``PlannedStep`` matches the
seeded values. This is the module_04 DoD leaf that proves the schema
converters ship a real contract, not a printed shape.
"""

from __future__ import annotations

import json

import jsonschema
import pytest

from ract.core.actions import (
    ACTION_MEMBERS,
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
from ract.providers.schema import (
    parse_action_dict,
    parse_planned_step_dict,
    to_anthropic_tool_use,
    to_json_schema_fallback,
    to_openai_structured_outputs,
)


def _seed_action(cls: type) -> dict[str, object]:
    if cls is WriteFileAction:
        return {
            "kind": "write_file",
            "path": "src/foo.py",
            "content": "x = 1\n",
            "rationale": "assumption-1",
            "parent_rootknots": ["rk-a", "rk-b"],
        }
    if cls is RunTestsAction:
        return {
            "kind": "run_tests",
            "selector": "tests/test_foo.py",
            "timeout_seconds": 60,
        }
    if cls is ReadFileAction:
        return {"kind": "read_file", "path": "src/foo.py", "rationale": "context"}
    if cls is SearchWorkspaceAction:
        return {
            "kind": "search_workspace",
            "query": "def compile",
            "glob": "src/**/*.py",
            "max_matches": 25,
        }
    if cls is ProposePredicateAction:
        return {
            "kind": "propose_predicate",
            "predicate_kind": "test",
            "invocation": {"type": "pytest", "selector": "tests/test_new.py"},
            "rationale": "new invariant",
            "required": True,
        }
    if cls is DeleteFileAction:
        return {
            "kind": "delete_file",
            "path": "src/dead.py",
            "rationale": "auction retired",
        }
    if cls is RequestHandshakeAction:
        return {
            "kind": "request_handshake",
            "handshake_kind": "tier2_network",
            "payload": {"host": "pypi.org"},
            "rationale": "install a dep",
        }
    if cls is EmitEventAction:
        return {
            "kind": "emit_event",
            "event_kind": "progress",
            "payload": {"iteration": 1},
            "manifest_digest_hex": "00" * 32,
        }
    raise AssertionError(f"missing seed for {cls!r}")


def _seed_planned_step(cls: type) -> dict[str, object]:
    return {
        "step_id": f"step-{cls.__name__}",
        "action": _seed_action(cls),
        "depends_on": [],
        "assumptions": [f"assumption-{cls.__name__}"],
        "postconditions": [],
    }


# ---------------------------------------------------------------------------
# OpenAI Structured Outputs
# ---------------------------------------------------------------------------


def test_openai_structured_outputs_shape() -> None:
    payload = to_openai_structured_outputs()
    assert payload["type"] == "json_schema"
    body = payload["json_schema"]
    assert body["strict"] is True
    assert body["name"]
    schema = body["schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "action" in schema["properties"]


@pytest.mark.parametrize("cls", ACTION_MEMBERS)
def test_openai_schema_round_trip(cls: type) -> None:
    payload = to_openai_structured_outputs()
    schema = payload["json_schema"]["schema"]
    seed = _seed_planned_step(cls)
    jsonschema.validate(instance=seed, schema=schema)
    parsed = parse_planned_step_dict(seed)
    assert isinstance(parsed, PlannedStep)
    assert type(parsed.action) is cls


# ---------------------------------------------------------------------------
# Anthropic tool use
# ---------------------------------------------------------------------------


def test_anthropic_tools_one_per_kind() -> None:
    tools = to_anthropic_tool_use()
    names = {t["name"] for t in tools}
    assert names == LEGAL_ACTION_KINDS
    for tool in tools:
        assert tool["input_schema"]["type"] == "object"
        assert tool["input_schema"]["additionalProperties"] is False
        assert tool["description"]


@pytest.mark.parametrize("cls", ACTION_MEMBERS)
def test_anthropic_tool_input_round_trip(cls: type) -> None:
    tools = to_anthropic_tool_use()
    seed_action = _seed_action(cls)
    tool = next(t for t in tools if t["name"] == seed_action["kind"])
    jsonschema.validate(instance=seed_action, schema=tool["input_schema"])
    parsed = parse_action_dict(seed_action)
    assert type(parsed) is cls


# ---------------------------------------------------------------------------
# JSON Schema fallback
# ---------------------------------------------------------------------------


def test_json_schema_fallback_carries_draft_id() -> None:
    schema = to_json_schema_fallback()
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["type"] == "object"


@pytest.mark.parametrize("cls", ACTION_MEMBERS)
def test_json_schema_fallback_round_trip(cls: type) -> None:
    schema = to_json_schema_fallback()
    seed = _seed_planned_step(cls)
    jsonschema.validate(instance=seed, schema=schema)
    parsed = parse_planned_step_dict(seed)
    assert type(parsed.action) is cls


def test_json_schema_fallback_rejects_unknown_kind() -> None:
    schema = to_json_schema_fallback()
    seed = {
        "step_id": "s1",
        "action": {"kind": "shell_exec", "cmd": "rm -rf /"},
        "depends_on": [],
        "assumptions": [],
        "postconditions": [],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=seed, schema=schema)


def test_openai_schema_dumps_to_json() -> None:
    """Sanity: the schema is JSON-serialisable."""
    payload = to_openai_structured_outputs()
    text = json.dumps(payload)
    assert "planned_step" in text
