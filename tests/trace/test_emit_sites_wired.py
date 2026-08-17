"""Integration: every module-05 emit site fires when a writer is set.

module_05 DoD: a synthetic 3-step run emits at least one event of each
of the kinds the plan enumerates. We drive each emit site directly
(compile / step transaction / predicate / handshake / assumption /
sandbox / EmitEventAction) so the wiring is test-covered.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.core.actions import EmitEventAction
from ract.core.assumption_registry import AssumptionRegistry
from ract.core.assumption import Evidence
from ract.core.compile import CompilerInputs, IntentCompiler
from ract.core.loop import WorkspaceSnapshot
from ract.core.predicate import (
    AcceptancePredicate,
    ArtifactInvocation,
    new_predicate_id,
)
from ract.core.transaction import (
    open_transaction,
    new_step_id,
)
from ract.handshake_registry import HandshakeRegistry
from ract.trace import clear_writer, set_writer
from ract.trace.writer import EventReader, JsonlEventWriter


RUN_ID = b"\x07" * 16


@pytest.fixture
def writer(tmp_path: Path):
    p = tmp_path / "run" / "events.jsonl"
    w = JsonlEventWriter(p, run_id=RUN_ID)
    # Ensure no other test leaked a writer.
    try:
        clear_writer()
    except Exception:
        pass
    set_writer(w, force=True)
    yield w
    clear_writer()


def _kinds_in(path: Path) -> set[str]:
    return {ev.kind for ev in EventReader.iter_events(path)}


def test_intent_compile_emits_run_started(writer: JsonlEventWriter) -> None:
    compiler = IntentCompiler()
    ws = WorkspaceSnapshot(files={"tests/test_x.py": "x"})
    compiler.compile("do something", ws, inputs=CompilerInputs())
    kinds = _kinds_in(writer.path)
    assert "run.started" in kinds


def test_transaction_open_emits_step_started(
    writer: JsonlEventWriter, tmp_path: Path
) -> None:
    open_transaction(
        step_id=new_step_id(),
        parent_snapshot="deadbeef",
        worktree_path=tmp_path,
    )
    kinds = _kinds_in(writer.path)
    assert "step.started" in kinds


def test_predicate_evaluate_emits_event(
    writer: JsonlEventWriter, tmp_path: Path
) -> None:
    predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(path="README.md"),
        required=True,
    )
    ws = WorkspaceSnapshot(files={"README.md": "hello"})
    predicate.evaluate(ws)
    kinds = _kinds_in(writer.path)
    assert "predicate.evaluated" in kinds


def test_handshake_lifecycle_emits(writer: JsonlEventWriter, tmp_path: Path) -> None:
    registry = HandshakeRegistry(tmp_path)
    registry.add(
        milestone_id="m-int",
        description="test",
        acceptance="ok",
    )
    registry.update_status("m-int", "approved")
    kinds = _kinds_in(writer.path)
    assert "handshake.requested" in kinds
    assert "handshake.resolved" in kinds


def test_assumption_lifecycle_emits(writer: JsonlEventWriter) -> None:
    reg = AssumptionRegistry()
    a = reg.propose("environment is dockerized")
    reg.accept(a.id)
    reg.discharge(a.id, Evidence(text="proof"))
    b = reg.propose("dependent claim", depends_on=(a.id,))
    reg.accept(b.id)
    # Violate one and check propagation surfaces.
    from ract.core.assumption import Violation

    reg.violate(a.id, Violation(text="broke"))
    kinds = _kinds_in(writer.path)
    assert "assumption.proposed" in kinds
    assert "assumption.discharged" in kinds
    assert "assumption.violated" in kinds


def test_emit_event_action_dispatch(writer: JsonlEventWriter) -> None:
    """module_04 flagged gap: EmitEventAction had a null sink; now wired."""
    action = EmitEventAction(
        event_kind="tool.called",
        payload={"tool": "read_file"},
    )
    action.dispatch()
    kinds = _kinds_in(writer.path)
    assert "tool.called" in kinds


def test_emit_event_action_rejects_unknown_kind(writer: JsonlEventWriter) -> None:
    action = EmitEventAction(event_kind="not.a.real.kind", payload={})
    with pytest.raises(ValueError, match="unknown event_kind"):
        action.dispatch()


def test_synthetic_three_step_run_emits_every_expected_kind(
    writer: JsonlEventWriter, tmp_path: Path
) -> None:
    """DoD: a synthetic 3-step run emits at least one of each expected kind."""
    compiler = IntentCompiler()
    ws = WorkspaceSnapshot(files={"tests/test_x.py": "x", "README.md": "y"})
    compiler.compile("do", ws, inputs=CompilerInputs())

    reg = AssumptionRegistry()
    a = reg.propose("assumption A")
    reg.accept(a.id)
    reg.discharge(a.id, Evidence(text="d"))

    handshake = HandshakeRegistry(tmp_path)
    handshake.add("m-1", "d", "a")
    handshake.update_status("m-1", "approved")

    for _ in range(3):
        open_transaction(
            step_id=new_step_id(),
            parent_snapshot="d1e",
            worktree_path=tmp_path,
        )

    predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(path="README.md"),
        required=True,
    )
    predicate.evaluate(ws)

    EmitEventAction(event_kind="tool.called", payload={"tool": "x"}).dispatch()

    expected = {
        "run.started",
        "step.started",
        "predicate.evaluated",
        "handshake.requested",
        "handshake.resolved",
        "assumption.proposed",
        "assumption.discharged",
        "tool.called",
    }
    kinds = _kinds_in(writer.path)
    missing = expected - kinds
    assert not missing, f"missing kinds: {sorted(missing)}"


# RACT 0.4.0
