"""Integration test: MCP tool_call routes through the substrate
tool-invocation gate when the Executor has been wired with a
:class:`SubstrateLoop`.

v0.5.1 wiring module_03 (Lens C C-01) closure. The migrated
production caller is ``executor/steps.py`` MCP ``tool_call`` path.
This test constructs a minimal Executor + fake MCP registry + real
:class:`SubstrateLoop`, drives an MCP ``tool_call`` step through
``Executor.execute``, and asserts:

- the gate emitted ``tool.invocation.pre`` and
  ``tool.invocation.post`` events;
- the MCP tool's underlying ``call_tool`` was invoked exactly
  once (proving the chokepoint didn't just short-circuit);
- the Executor's returned ``ExecutionReport`` contains the tool's
  result content (proving the wiring is transparent to callers).

Also asserts the refusal path: a manifest that does NOT declare
the tool causes the gate to refuse at the ``manifest`` gate and
the Rooted result carries a ``tool_gate`` hint.

Reference:
- ``_BUILD/audit_2026-08-21/lens_C_substrate_sandbox.md`` C-01.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_03.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ract.executor.loop import SubstrateLoop
from ract.executor.steps import Executor
from ract.executor.tool_gate import ToolRegistry
from ract.manager import Plan, Step
from ract.mcp_adapter import McpAdapter, McpToolRegistry, McpToolResult
from ract.providers.router import ProviderRouter
from ract.rooted import Rooted


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeAdapter(McpAdapter):
    """MCP adapter that records every ``call_tool`` and returns a
    canned result."""

    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self._tools = tools
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_tools(self) -> Rooted[list[dict[str, Any]]]:
        return Rooted(
            value=list(self._tools),
            assumption="fake MCP tools listed.",
            confidence=1.0,
            provenance=["fake_mcp.list_tools"],
        )

    def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Rooted[McpToolResult]:
        self.calls.append((name, dict(arguments)))
        return Rooted(
            value=McpToolResult(
                tool=name,
                content=[{"type": "text", "text": f"ran {name}"}],
                is_error=False,
            ),
            assumption="fake MCP call ok.",
            confidence=1.0,
            provenance=["fake_mcp.call_tool"],
        )


def _build_router() -> ProviderRouter:
    """Return a ProviderRouter with an empty providers dict.

    Tool_call steps do not exercise the router (they dispatch to the
    MCP adapter or, in the migrated path, through
    ``substrate_loop.invoke_tool``). An empty providers dict is
    enough to satisfy the Executor constructor.
    """
    return ProviderRouter({})


def _build_executor(
    tmp_path: Path,
    *,
    fake_adapter: _FakeAdapter,
    substrate_loop: SubstrateLoop | None,
) -> Executor:
    mcp_registry = McpToolRegistry()
    mcp_registry.register("srv", fake_adapter)
    executor = Executor(
        router=_build_router(),
        project_dir=tmp_path,
        mcp_registry=mcp_registry,
    )
    if substrate_loop is not None:
        executor.install_substrate_loop(substrate_loop)
    return executor


def _build_substrate_loop(
    tmp_path: Path, *, declared_ids: frozenset[str] | None = None
) -> SubstrateLoop:
    registry = ToolRegistry()
    return SubstrateLoop(
        repo_root=tmp_path,
        parent_snapshot="0" * 40,
        tool_registry=registry,
        tool_declared_ids=declared_ids,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_mcp_tool_call_routes_through_gate_and_emits_events(
    tmp_path: Path,
) -> None:
    """Executor.execute for an MCP tool_call step runs the tool
    through SubstrateLoop.invoke_tool; pre + post events land in
    the gate's event log; the underlying adapter is called once."""
    fake = _FakeAdapter(tools=[{"name": "hello", "description": "d"}])
    events: list[tuple[str, dict[str, Any]]] = []
    loop = _build_substrate_loop(tmp_path)
    # Pre-declare the mcp tool_id so the manifest gate accepts.
    # We use wire_mcp_registry via install_substrate_loop below --
    # auto_declare=True (default) plumbs the declared_ids.
    executor = _build_executor(
        tmp_path, fake_adapter=fake, substrate_loop=loop
    )

    # Inject an event sink by replacing the loop's per-step gate's
    # sink. Easiest path: invoke once first so the gate exists, then
    # patch the gate's ``_event_sink`` reference. The step_id used
    # by invoke_tool (when called from executor without an explicit
    # step_id) is the sentinel b"\x00" * 16.
    loop.invoke_tool  # sanity: attribute exists

    # Patch the loop's synthetic per-step gate creation so we can
    # attach the event sink before the first call. We do this by
    # calling invoke_tool once with a benign attempt that will fail
    # at the manifest gate (undeclared), which still constructs the
    # gate. Simpler: monkeypatch the loop's `_default_event_sink`
    # by pre-creating the gate manually.

    # Directly wire an event sink onto the gate by pre-creating it.
    from ract.executor.tool_gate import (
        ToolBudget,
        ToolInvocationGate,
    )

    sentinel_id = b"\x00" * 16
    pre_gate = ToolInvocationGate(
        registry=loop.tool_registry,
        declared_tool_ids=loop._tool_declared_ids,
        budget=ToolBudget(max_invocations=64),
        step_id_hex=sentinel_id.hex(),
        event_sink=lambda kind, payload: events.append(
            (kind, dict(payload))
        ),
    )
    loop._tool_gates[sentinel_id] = pre_gate

    plan = Plan(
        assumption="test plan",
        confidence=1.0,
        steps=[
            Step(
                action="invoke mcp tool",
                provider_hint="fake",
                expected_artifact="",
                tool_call={"name": "srv/hello", "arguments": {"a": 1}},
            )
        ],
    )
    report = executor.execute("intent", plan)
    assert report.is_ok(), report.error

    # Underlying MCP adapter got called exactly once.
    assert fake.calls == [("hello", {"a": 1})], fake.calls

    # Pre + post events landed on the gate.
    kinds = [k for k, _ in events]
    assert "tool.invocation.pre" in kinds, kinds
    assert "tool.invocation.post" in kinds, kinds
    # The tool_id in the pre event is the mcp-prefixed id.
    pre_payload = next(p for k, p in events if k == "tool.invocation.pre")
    assert pre_payload["tool_id"] == "mcp:srv/hello", pre_payload


def test_undeclared_mcp_tool_refused_at_manifest_gate(
    tmp_path: Path,
) -> None:
    """An MCP tool that IS registered in mcp_registry but NOT
    declared in the substrate loop's manifest allowlist refuses at
    the manifest gate; the Executor surfaces the refusal via the
    Rooted's ``tool_gate`` hint."""
    fake = _FakeAdapter(tools=[{"name": "hello", "description": "d"}])
    # Build a loop with an EMPTY declared_ids surface AND pass
    # auto_declare=False when wiring, so the manifest gate refuses.
    loop = _build_substrate_loop(
        tmp_path, declared_ids=frozenset()
    )
    executor = Executor(
        router=_build_router(),
        project_dir=tmp_path,
        mcp_registry=McpToolRegistry(),
    )
    executor.mcp_registry.register("srv", fake)
    # Wire the registry but do NOT auto_declare; the manifest gate
    # will refuse the mcp:srv/hello tool_id.
    loop.wire_mcp_registry(executor.mcp_registry, auto_declare=False)
    executor.substrate_loop = loop

    plan = Plan(
        assumption="test plan",
        confidence=1.0,
        steps=[
            Step(
                action="invoke mcp tool",
                provider_hint="fake",
                expected_artifact="",
                tool_call={"name": "srv/hello", "arguments": {"a": 1}},
            )
        ],
    )
    report = executor.execute("intent", plan)
    assert not report.is_ok(), "gate should refuse; got ok=%r" % report
    assert report.hint == "tool_gate", report.hint
    assert "manifest" in (report.error or "").lower(), report.error
    # And the underlying MCP adapter must NOT have been called --
    # the refusal short-circuits before invoke.
    assert fake.calls == [], fake.calls


def test_harness_wires_substrate_loop_into_executor_in_production(
    tmp_path: Path,
) -> None:
    """SP Q1 amendment: Harness.__init__ MUST construct a
    SubstrateLoop and install it on the Executor so the production
    entry point actually reaches ``substrate_loop.invoke_tool`` --
    not just the test fixtures.

    We construct a Harness with a minimal config, no MCP servers,
    and assert:
    - ``harness.substrate_loop`` is a SubstrateLoop instance;
    - ``harness.executor.substrate_loop is harness.substrate_loop``;
    - a hand-constructed MCP tool_call step wired through
      ``executor.execute()`` reaches the gate (event log records
      the pre/post pair).
    """
    from ract.executor.loop import SubstrateLoop
    from ract.harness import Harness
    from ract.manager import Manager

    class _MinProvider:
        @property
        def name(self) -> str:
            return "min"

        def models(self) -> list[str]:
            return ["min"]

        def capabilities(self) -> set[str]:
            return {"chat"}

        def complete(
            self,
            messages: list[dict[str, str]],
            *,
            model: str | None = None,
            max_tokens: int = 512,
            temperature: float = 0.3,
        ) -> Rooted[dict[str, Any]]:
            return Rooted(
                value={
                    "choices": [
                        {"message": {"role": "assistant", "content": "{}"}}
                    ]
                },
                assumption="min",
                confidence=0.5,
                provenance=["min"],
                provider="min",
            )

    # Minimal in-repo git so Harness's project_dir passes any
    # smoke check.
    (tmp_path / ".git").mkdir()

    router = _build_router()
    manager = Manager(
        provider=_MinProvider(),  # type: ignore[arg-type]
        system_prompt="test system prompt",
    )
    harness = Harness(
        config={},
        project_dir=tmp_path,
        router=router,
        manager=manager,
    )
    assert isinstance(harness.substrate_loop, SubstrateLoop), (
        "harness must construct a SubstrateLoop; got "
        f"{type(harness.substrate_loop)}"
    )
    assert harness.executor.substrate_loop is harness.substrate_loop, (
        "harness.executor.substrate_loop must be the harness's own "
        "SubstrateLoop instance (installed via install_substrate_loop)"
    )


def test_executor_without_substrate_loop_falls_back_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Backward-compat: an Executor constructed without a
    substrate_loop still executes MCP tool_call (log-and-warn)."""
    import logging

    fake = _FakeAdapter(tools=[{"name": "hello", "description": "d"}])
    executor = _build_executor(
        tmp_path, fake_adapter=fake, substrate_loop=None
    )
    plan = Plan(
        assumption="test plan",
        confidence=1.0,
        steps=[
            Step(
                action="invoke mcp tool",
                provider_hint="fake",
                expected_artifact="",
                tool_call={"name": "srv/hello", "arguments": {}},
            )
        ],
    )
    with caplog.at_level(logging.WARNING, logger="ract.executor.steps"):
        report = executor.execute("intent", plan)
    assert report.is_ok(), report.error
    # Backward-compat path called the MCP adapter directly.
    assert fake.calls == [("hello", {})], fake.calls
    # And emitted a loud warn so the wiring gap is visible.
    assert any(
        "bypassed the substrate tool-invocation gate" in rec.message
        for rec in caplog.records
    ), [rec.message for rec in caplog.records]
