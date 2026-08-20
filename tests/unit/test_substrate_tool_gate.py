"""SubstrateLoop tool-invocation gate -- unit tests (v0.5.1 module_05).

Every tool call in a substrate step goes through one chokepoint:
``SubstrateLoop.invoke_tool`` -> ``ToolInvocationGate.invoke`` (see
``src/ract/executor/tool_gate.py``). This file locks the four gates
in order (manifest, args, budget, registry) plus the structured
refusal contract (``ToolInvocationRefused``) plus the event surface
(``tool.invocation.pre|post|refused``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.executor.tool_gate import (
    ToolArgSchema,
    ToolArgSpec,
    ToolBudget,
    ToolDefinition,
    ToolInvocationGate,
    ToolInvocationRefused,
    ToolRegistry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            tool_id="fs.read",
            schema=ToolArgSchema(
                args=(
                    ToolArgSpec(name="path", type_=str),
                    ToolArgSpec(name="max_bytes", type_=int, optional=True),
                )
            ),
            call=lambda path, max_bytes=None: f"read:{path}",
        )
    )
    reg.register(
        ToolDefinition(
            tool_id="fs.write",
            schema=ToolArgSchema(
                args=(
                    ToolArgSpec(name="path", type_=str),
                    ToolArgSpec(name="content", type_=str),
                )
            ),
            call=lambda path, content: len(content),
        )
    )
    reg.freeze()
    return reg


def _make_gate(
    *,
    declared: frozenset[str] = frozenset({"fs.read", "fs.write"}),
    budget_max: int = 8,
    sink: list | None = None,
) -> tuple[ToolInvocationGate, list]:
    events = sink if sink is not None else []
    gate = ToolInvocationGate(
        registry=_make_registry(),
        declared_tool_ids=declared,
        budget=ToolBudget(max_invocations=budget_max),
        step_id_hex="a" * 32,
        event_sink=lambda kind, payload: events.append((kind, payload)),
    )
    return gate, events


# ---------------------------------------------------------------------------
# Successful invocation
# ---------------------------------------------------------------------------


def test_invoke_success_emits_pre_and_post_events() -> None:
    gate, events = _make_gate()
    result = gate.invoke("fs.read", {"path": "src/x.py"})
    assert result == "read:src/x.py"
    kinds = [k for k, _ in events]
    assert kinds == ["tool.invocation.pre", "tool.invocation.post"]
    pre_payload = events[0][1]
    post_payload = events[1][1]
    assert pre_payload["tool_id"] == "fs.read"
    assert post_payload["ok"] is True
    assert post_payload["latency_ms"] >= 0
    assert post_payload["result_size_bytes"] > 0


def test_invoke_records_success_in_history() -> None:
    gate, _events = _make_gate()
    gate.invoke("fs.read", {"path": "a.py"})
    gate.invoke("fs.write", {"path": "b.py", "content": "hi"})
    records = gate.records
    assert len(records) == 2
    assert all(r.ok for r in records)
    assert [r.tool_id for r in records] == ["fs.read", "fs.write"]


def test_optional_arg_omitted_admissible() -> None:
    gate, _ = _make_gate()
    # max_bytes optional -- omission MUST be admissible.
    gate.invoke("fs.read", {"path": "a.py"})


# ---------------------------------------------------------------------------
# Gate 1: manifest-declared refusal
# ---------------------------------------------------------------------------


def test_manifest_gate_refuses_undeclared_tool() -> None:
    gate, events = _make_gate(declared=frozenset({"fs.read"}))
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke("fs.write", {"path": "a.py", "content": "x"})
    assert exc.value.gate == "manifest"
    assert exc.value.tool_id == "fs.write"
    refusal_events = [k for k, _ in events if k == "tool.invocation.refused"]
    assert refusal_events == ["tool.invocation.refused"]


def test_manifest_gate_refusal_details_carry_allowlist() -> None:
    gate, _ = _make_gate(declared=frozenset({"fs.read"}))
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke("net.fetch", {"url": "https://x"})
    assert "declared_ids" in exc.value.details
    assert exc.value.details["declared_ids"] == ["fs.read"]


# ---------------------------------------------------------------------------
# Gate 2: registry (declared but no implementation)
# ---------------------------------------------------------------------------


def test_registry_gate_refuses_when_no_impl() -> None:
    # tool_id is on the declared_ids allowlist but not in the registry.
    reg = ToolRegistry()
    reg.freeze()
    events: list = []
    gate = ToolInvocationGate(
        registry=reg,
        declared_tool_ids=frozenset({"fs.read"}),
        step_id_hex="b" * 32,
        event_sink=lambda k, p: events.append((k, p)),
    )
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke("fs.read", {"path": "a"})
    assert exc.value.gate == "registry"


# ---------------------------------------------------------------------------
# Gate 3: args conformance
# ---------------------------------------------------------------------------


def test_args_gate_refuses_extra_arg() -> None:
    gate, _ = _make_gate()
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke("fs.read", {"path": "a", "bogus": 1})
    assert exc.value.gate == "args"
    assert "bogus" in exc.value.details.get("unknown_args", [])


def test_args_gate_refuses_missing_required_arg() -> None:
    gate, _ = _make_gate()
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke("fs.read", {})
    assert exc.value.gate == "args"


def test_args_gate_refuses_type_mismatch() -> None:
    gate, _ = _make_gate()
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke("fs.read", {"path": 123})
    assert exc.value.gate == "args"


def test_args_gate_bool_is_not_int() -> None:
    """Guard against Python's ``bool is int`` foot-gun."""
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            tool_id="counter",
            schema=ToolArgSchema(args=(ToolArgSpec(name="n", type_=int),)),
            call=lambda n: n * 2,
        )
    )
    reg.freeze()
    gate = ToolInvocationGate(
        registry=reg,
        declared_tool_ids=frozenset({"counter"}),
    )
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke("counter", {"n": True})
    assert exc.value.gate == "args"


# ---------------------------------------------------------------------------
# Gate 4: budget
# ---------------------------------------------------------------------------


def test_budget_gate_refuses_when_exhausted() -> None:
    gate, _ = _make_gate(budget_max=2)
    gate.invoke("fs.read", {"path": "a"})
    gate.invoke("fs.read", {"path": "b"})
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke("fs.read", {"path": "c"})
    assert exc.value.gate == "budget"
    assert exc.value.details["used"] == 2
    assert exc.value.details["max"] == 2


def test_budget_not_consumed_by_earlier_gate_refusal() -> None:
    """A manifest refusal must NOT consume a budget slot -- the tool
    never ran."""
    gate, _ = _make_gate(budget_max=1, declared=frozenset({"fs.read"}))
    with pytest.raises(ToolInvocationRefused):
        gate.invoke("net.fetch", {"url": "https://x"})
    # Slot should still be available.
    assert gate.budget.remaining() == 1
    gate.invoke("fs.read", {"path": "a"})
    assert gate.budget.remaining() == 0


# ---------------------------------------------------------------------------
# Tool exception path
# ---------------------------------------------------------------------------


def test_tool_exception_still_emits_post_and_records_failure() -> None:
    reg = ToolRegistry()

    def _boom() -> None:
        raise ValueError("boom")

    reg.register(
        ToolDefinition(
            tool_id="boom",
            schema=ToolArgSchema(),
            call=_boom,
        )
    )
    reg.freeze()
    events: list = []
    gate = ToolInvocationGate(
        registry=reg,
        declared_tool_ids=frozenset({"boom"}),
        event_sink=lambda k, p: events.append((k, p)),
    )
    with pytest.raises(ValueError, match="boom"):
        gate.invoke("boom", {})
    kinds = [k for k, _ in events]
    assert kinds == ["tool.invocation.pre", "tool.invocation.post"]
    assert events[1][1]["ok"] is False
    assert events[1][1]["exception"] == "ValueError"


# ---------------------------------------------------------------------------
# Registry immutability
# ---------------------------------------------------------------------------


def test_frozen_registry_refuses_new_registrations() -> None:
    reg = ToolRegistry()
    reg.freeze()
    with pytest.raises(RuntimeError, match="frozen"):
        reg.register(
            ToolDefinition(
                tool_id="x",
                schema=ToolArgSchema(),
                call=lambda: None,
            )
        )


def test_duplicate_tool_id_refused() -> None:
    reg = ToolRegistry()
    defn = ToolDefinition(
        tool_id="dup",
        schema=ToolArgSchema(),
        call=lambda: None,
    )
    reg.register(defn)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(defn)


# ---------------------------------------------------------------------------
# ToolArgSpec type gate
# ---------------------------------------------------------------------------


def test_toolargspec_refuses_unknown_type() -> None:
    with pytest.raises(ValueError, match="not in the allowed set"):
        ToolArgSpec(name="x", type_=Path)  # Path is not allowed


# ---------------------------------------------------------------------------
# args_repr bounding for privacy
# ---------------------------------------------------------------------------


def test_args_repr_bounded_to_prevent_secret_leak() -> None:
    gate, events = _make_gate()
    big = "x" * 2000
    gate.invoke("fs.write", {"path": "b.py", "content": big})
    pre_payload = events[0][1]
    args_repr = pre_payload["args_repr"]
    assert len(args_repr) <= 512


# RACT 0.5.1
