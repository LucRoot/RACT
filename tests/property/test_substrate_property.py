"""Substrate invariants -- property tests (v0.5.1 module_05).

Invariants asserted across random configurations:

1. **Tool-gate refusal is structural.** For any tool_id not on the
   declared_ids allowlist, ``ToolInvocationGate.invoke`` refuses
   with ``gate="manifest"`` regardless of the args shape.
2. **Budget is monotonic.** ``used`` never decreases; ``remaining ==
   max - used`` throughout the invocation sequence.
3. **Compensator stack LIFO drain.** For any install order, drain
   returns compensators in reverse install order (last-in first-out).
4. **Environ allowlist is deny-by-default.** For any process env,
   a name absent from ``manifest_passthrough ∪ allowlist_file ∪
   DEFAULT_ALLOWLIST`` never appears in the result env.
"""

from __future__ import annotations

import string

import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, given, settings

from ract.executor.commit_compensator import CommitCompensator, CompensatorStack
from ract.executor.tool_gate import (
    ToolArgSchema,
    ToolBudget,
    ToolDefinition,
    ToolInvocationGate,
    ToolInvocationRefused,
    ToolRegistry,
)
from ract.security.sandbox_env import (
    _is_never_passthrough,
    build_sandbox_env,
)


_TOOL_IDS = st.text(
    alphabet=string.ascii_letters + string.digits + "._",
    min_size=1,
    max_size=32,
)


@st.composite
def _registered_registry(draw) -> tuple[ToolRegistry, frozenset[str]]:
    ids = draw(st.lists(_TOOL_IDS, min_size=1, max_size=5, unique=True))
    reg = ToolRegistry()
    for tid in ids:
        reg.register(
            ToolDefinition(
                tool_id=tid,
                schema=ToolArgSchema(),
                call=lambda **kwargs: None,
            )
        )
    reg.freeze()
    return reg, frozenset(ids)


# ---------------------------------------------------------------------------
# Invariant 1 -- tool-gate manifest refusal
# ---------------------------------------------------------------------------


@given(
    data=st.data(),
    intruder=_TOOL_IDS,
)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_tool_gate_refuses_any_undeclared_id(data, intruder: str) -> None:
    reg, declared = data.draw(_registered_registry())
    if intruder in declared:
        return  # not the case we test
    gate = ToolInvocationGate(
        registry=reg,
        declared_tool_ids=declared,
        budget=ToolBudget(max_invocations=100),
    )
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke(intruder, {})
    assert exc.value.gate == "manifest"


# ---------------------------------------------------------------------------
# Invariant 2 -- budget monotonicity
# ---------------------------------------------------------------------------


@given(max_slots=st.integers(min_value=1, max_value=20))
@settings(max_examples=20, deadline=None)
def test_budget_used_never_decreases(max_slots: int) -> None:
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            tool_id="t",
            schema=ToolArgSchema(),
            call=lambda: None,
        )
    )
    reg.freeze()
    gate = ToolInvocationGate(
        registry=reg,
        declared_tool_ids=frozenset({"t"}),
        budget=ToolBudget(max_invocations=max_slots),
    )
    prev_used = 0
    for i in range(max_slots):
        gate.invoke("t", {})
        assert gate.budget.used == i + 1
        assert gate.budget.used >= prev_used
        assert gate.budget.remaining() == max_slots - gate.budget.used
        prev_used = gate.budget.used
    # Next call MUST refuse at the budget gate.
    with pytest.raises(ToolInvocationRefused) as exc:
        gate.invoke("t", {})
    assert exc.value.gate == "budget"


# ---------------------------------------------------------------------------
# Invariant 3 -- compensator LIFO
# ---------------------------------------------------------------------------


@given(
    entries=st.lists(
        st.text(alphabet="abcdef0123456789", min_size=8, max_size=8),
        min_size=1,
        max_size=6,
    )
)
@settings(max_examples=20, deadline=None)
def test_compensator_drain_is_lifo(entries: list[str]) -> None:
    from pathlib import Path

    events: list = []

    class _NullComp(CommitCompensator):
        # Override apply so we do not actually shell git; the invariant
        # under test is stack ordering, not git behaviour (covered
        # separately in tests/unit/test_git_commit_compensator.py).
        def apply(self) -> bool:  # type: ignore[override]
            if self.applied:
                from ract.executor.commit_compensator import (
                    CompensatorAlreadyApplied,
                )

                raise CompensatorAlreadyApplied
            self.applied = True
            return True

    stack = CompensatorStack(event_sink=lambda k, p: events.append((k, p)))
    installed_order: list[str] = []
    for sha in entries:
        comp = _NullComp(
            repo_root=Path("."),
            branch="main",
            sha_before="0" * 40,
            sha_after=sha,
        )
        stack.install(comp)
        installed_order.append(sha)

    outcomes = stack.drain(reason="T2_property")
    drained_shas = [comp.sha_after for comp, _ in outcomes]
    assert drained_shas == list(reversed(installed_order))


# ---------------------------------------------------------------------------
# Invariant 4 -- environ allowlist deny-by-default
# ---------------------------------------------------------------------------


@st.composite
def _env_map(draw) -> dict[str, str]:
    # Draw a mix of legitimate-looking and secret-looking names.
    n = draw(st.integers(min_value=1, max_value=10))
    keys = draw(
        st.lists(
            st.text(
                alphabet=string.ascii_uppercase + "_",
                min_size=1,
                max_size=24,
            ),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )
    values = draw(
        st.lists(st.text(min_size=0, max_size=32), min_size=n, max_size=n)
    )
    return dict(zip(keys, values))


@given(env=_env_map(), passthrough_size=st.integers(min_value=0, max_value=4))
@settings(max_examples=30, deadline=None)
def test_env_absent_from_result_unless_allowlisted(
    env: dict[str, str], passthrough_size: int
) -> None:
    # Draw a random subset of env keys to allowlist.
    keys = list(env.keys())
    passthrough = tuple(keys[:passthrough_size])
    result = build_sandbox_env(
        process_env=env,
        manifest_passthrough=passthrough,
        include_default=False,
    )
    union = set(passthrough)
    for name in env:
        # SP Q3(a) amendment: predicate widened from exact-name
        # ``NEVER_PASSTHROUGH`` set to case-insensitive prefix
        # families via ``_is_never_passthrough``. Property test
        # follows the same predicate.
        if name in union and not _is_never_passthrough(name):
            # Present because it was allowlisted.
            assert result.env.get(name) == env[name]
        else:
            # Absent because it was not on ANY allowlist (or was
            # denied by the widened NEVER_PASSTHROUGH predicate).
            assert name not in result.env


# RACT 0.5.1
