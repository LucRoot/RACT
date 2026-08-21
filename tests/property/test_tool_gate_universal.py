"""Property test: the four-gate tool-invocation chokepoint.

v0.5.1 wiring module_03 (Lens C C-01) closure. The Lens C audit's
core claim was that the substrate's tool-invocation gate is a
CHOKEPOINT: a tool call has ONE way in and the gate cannot be
bypassed by construction. This test drives the gate with random
tool_id / args / manifest / registry / budget combinations and
asserts:

- if ``tool_id`` is NOT in the manifest allowlist, the gate
  refuses at the ``manifest`` gate (regardless of registry/args/
  budget state);
- if declared but not registered, the gate refuses at ``registry``;
- if declared and registered but args non-conforming, the gate
  refuses at ``args`` (unknown key OR type mismatch OR missing
  required);
- if all above pass but budget exhausted, the gate refuses at
  ``budget``;
- if all four pass, ``invoke`` proceeds and returns the tool's
  result.

The property test uses hypothesis strategies to sample the tuple
space; each refusal path is asserted by the ``gate`` field on
:class:`ToolInvocationRefused`.

Reference:
- ``_BUILD/audit_2026-08-21/lens_C_substrate_sandbox.md`` C-01.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_03.md``.
"""

from __future__ import annotations

import string

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from ract.executor.tool_gate import (
    ToolArgSchema,
    ToolArgSpec,
    ToolBudget,
    ToolDefinition,
    ToolInvocationGate,
    ToolInvocationRefused,
    ToolRegistry,
)


_TOOL_ID_ALPHABET = string.ascii_lowercase + string.digits + "_"


def _tool_ids():
    return st.text(
        alphabet=_TOOL_ID_ALPHABET, min_size=1, max_size=12
    )


def _arg_names():
    return st.text(
        alphabet=string.ascii_lowercase + "_", min_size=1, max_size=8
    )


def _arg_values():
    # Restrict to scalars the schema knows about.
    return st.one_of(
        st.text(max_size=32),
        st.integers(min_value=-1_000, max_value=1_000),
        st.floats(
            allow_nan=False, allow_infinity=False, width=32
        ),
        st.booleans(),
    )


def _build_registry_with_one_tool(
    tool_id: str, arg_name: str, arg_type: type
) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            tool_id=tool_id,
            schema=ToolArgSchema(
                args=(ToolArgSpec(arg_name, arg_type, optional=False),)
            ),
            call=lambda **kw: {"echo": kw},
        )
    )
    return reg


@given(
    call_id=_tool_ids(),
    declared=st.lists(_tool_ids(), min_size=0, max_size=4, unique=True),
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.filter_too_much],
    deadline=None,
)
def test_manifest_gate_refuses_undeclared(
    call_id: str, declared: list[str]
) -> None:
    """When ``call_id`` is not in the declared set, the manifest
    gate must refuse."""
    # Ensure the invocation is UNDECLARED.
    declared_set = frozenset(declared) - {call_id}
    reg = _build_registry_with_one_tool(call_id, "x", str)
    gate = ToolInvocationGate(
        registry=reg,
        declared_tool_ids=declared_set,
        budget=ToolBudget(max_invocations=8),
    )
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke(call_id, {"x": "value"})
    assert exc.value.gate == "manifest"
    assert exc.value.tool_id == call_id


@given(
    tool_id=_tool_ids(),
    other_id=_tool_ids(),
)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.filter_too_much],
    deadline=None,
)
def test_registry_gate_refuses_declared_but_unregistered(
    tool_id: str, other_id: str
) -> None:
    """When ``tool_id`` is declared but the registry has no
    implementation, the registry gate must refuse."""
    if tool_id == other_id:
        return  # collapse -- registry would have it
    reg = _build_registry_with_one_tool(other_id, "x", str)
    gate = ToolInvocationGate(
        registry=reg,
        declared_tool_ids=frozenset({tool_id}),
        budget=ToolBudget(max_invocations=8),
    )
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke(tool_id, {"x": "value"})
    assert exc.value.gate == "registry"


@given(
    unknown_arg=_arg_names(),
    unknown_value=_arg_values(),
)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.filter_too_much],
    deadline=None,
)
def test_args_gate_refuses_unknown_key(
    unknown_arg: str, unknown_value: object
) -> None:
    """An arg key the tool did not declare must refuse at the
    ``args`` gate."""
    if unknown_arg == "target":
        return  # collapse -- would be a valid key
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            tool_id="probe",
            schema=ToolArgSchema(
                args=(ToolArgSpec("target", str, optional=False),)
            ),
            call=lambda **kw: kw,
        )
    )
    gate = ToolInvocationGate(
        registry=reg,
        declared_tool_ids=frozenset({"probe"}),
        budget=ToolBudget(max_invocations=8),
    )
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke(
            "probe",
            {"target": "ok", unknown_arg: unknown_value},
        )
    assert exc.value.gate == "args"


@given(bad_value=st.integers(min_value=-100, max_value=100))
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.filter_too_much],
    deadline=None,
)
def test_args_gate_refuses_type_mismatch(bad_value: int) -> None:
    """An arg type that doesn't match the declared spec must refuse
    at the ``args`` gate."""
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            tool_id="probe",
            schema=ToolArgSchema(
                args=(ToolArgSpec("target", str, optional=False),)
            ),
            call=lambda **kw: kw,
        )
    )
    gate = ToolInvocationGate(
        registry=reg,
        declared_tool_ids=frozenset({"probe"}),
        budget=ToolBudget(max_invocations=8),
    )
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke("probe", {"target": bad_value})
    assert exc.value.gate == "args"


@given(n_pre_invocations=st.integers(min_value=1, max_value=8))
@settings(
    max_examples=25,
    suppress_health_check=[HealthCheck.filter_too_much],
    deadline=None,
)
def test_budget_gate_refuses_when_exhausted(
    n_pre_invocations: int,
) -> None:
    """After the budget is exhausted, the next call must refuse at
    the ``budget`` gate."""
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            tool_id="probe",
            schema=ToolArgSchema(
                args=(ToolArgSpec("target", str, optional=False),)
            ),
            call=lambda **kw: {"ok": True},
        )
    )
    gate = ToolInvocationGate(
        registry=reg,
        declared_tool_ids=frozenset({"probe"}),
        budget=ToolBudget(max_invocations=n_pre_invocations),
    )
    for _ in range(n_pre_invocations):
        gate.invoke("probe", {"target": "ok"})
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke("probe", {"target": "over"})
    assert exc.value.gate == "budget"


def test_all_gates_pass_returns_tool_result() -> None:
    """When manifest + registry + args + budget all pass, the tool
    returns its result to the caller."""
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            tool_id="probe",
            schema=ToolArgSchema(
                args=(ToolArgSpec("target", str, optional=False),)
            ),
            call=lambda **kw: {"echoed": kw["target"]},
        )
    )
    gate = ToolInvocationGate(
        registry=reg,
        declared_tool_ids=frozenset({"probe"}),
        budget=ToolBudget(max_invocations=4),
    )
    result = gate.invoke("probe", {"target": "hello"})
    assert result == {"echoed": "hello"}


def test_four_gates_check_in_declared_order() -> None:
    """A single invocation that would fail multiple gates must
    refuse at the FIRST gate in evaluation order (manifest,
    registry, args, budget). Verifies the gate cascade is
    deterministic and short-circuits on first failure."""
    reg = ToolRegistry()
    # Register a tool but do NOT declare it in the manifest set.
    reg.register(
        ToolDefinition(
            tool_id="probe",
            schema=ToolArgSchema(
                args=(ToolArgSpec("target", str, optional=False),)
            ),
            call=lambda **kw: kw,
        )
    )
    gate = ToolInvocationGate(
        registry=reg,
        # Empty declared set -> the manifest gate MUST fire first
        # even though the registry has the tool AND the args are
        # wrong AND the budget is 0.
        declared_tool_ids=frozenset(),
        budget=ToolBudget(max_invocations=0),
    )
    with pytest.raises(ToolInvocationRefused) as exc:
        # Type mismatch AND unknown key AND missing required arg.
        gate.invoke("probe", {"bogus": 42})
    assert exc.value.gate == "manifest", (
        "gate cascade must refuse at first failure (manifest); "
        f"got {exc.value.gate!r}"
    )


def test_refusal_emits_event_and_records() -> None:
    """A refusal must record + emit before it raises, so the audit
    surface is populated even when the caller catches the
    exception."""
    events: list[tuple[str, dict]] = []
    reg = ToolRegistry()
    gate = ToolInvocationGate(
        registry=reg,
        declared_tool_ids=frozenset(),
        budget=ToolBudget(max_invocations=4),
        event_sink=lambda kind, payload: events.append((kind, payload)),
    )
    with pytest.raises(ToolInvocationRefused):
        gate.invoke("undeclared", {"x": 1})
    # tool.invocation.refused must have landed BEFORE the raise.
    assert any(k == "tool.invocation.refused" for k, _ in events), events
    # Records must include the refusal.
    assert len(gate.records) == 1
    rec = gate.records[0]
    assert rec.ok is False
    assert rec.refused_gate == "manifest"


def test_successful_invocation_emits_pre_and_post_events() -> None:
    """A successful invocation emits both ``tool.invocation.pre`` and
    ``tool.invocation.post`` events (in that order), so the audit log
    reflects the full lifecycle."""
    events: list[tuple[str, dict]] = []
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            tool_id="probe",
            schema=ToolArgSchema(
                args=(ToolArgSpec("target", str, optional=False),)
            ),
            call=lambda **kw: {"ok": kw["target"]},
        )
    )
    gate = ToolInvocationGate(
        registry=reg,
        declared_tool_ids=frozenset({"probe"}),
        budget=ToolBudget(max_invocations=4),
        event_sink=lambda kind, payload: events.append((kind, payload)),
    )
    gate.invoke("probe", {"target": "hi"})
    kinds = [k for k, _ in events]
    assert kinds == ["tool.invocation.pre", "tool.invocation.post"], kinds
