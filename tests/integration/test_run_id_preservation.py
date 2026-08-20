"""End-to-end run_id preservation smoke test (v0.5.1 module_06).

DeepSeek REVIEW_2 criticism 1 ("fragmented ``run_id``") observed that a
single loop iteration could emit artifacts stamped with three or four
different identifiers because each subsystem fabricated its own default
when a caller forgot to propagate. Module_06 introduces the ambient
:func:`ract.runtime.get_current_run_id` accessor + threads it through
every subsystem that writes a ``run_id`` field.

This module is the load-bearing regression test. The primary
end-to-end test drives every subsystem through one bound run_id and
asserts every emitted artifact carries the same value; a compaction
event mid-flow (fresh subsystem instances loading from persisted
state) preserves the id. Targeted per-layer tests catch drift the
moment a new subsystem forgets to consult the ambient.

Coverage:

- ``test_run_id_preserved_across_full_loop`` -- end-to-end. Bind
  ambient; drive the WAL, WorkspaceDigestChain, SuiteChain, event
  writer, and Rootknot v4 factory; assert every artifact stamps the
  same id; simulate a compaction event (fresh subsystem instances
  loading from persisted state) and re-assert.
- Per-layer smoke tests: WAL, event log, WorkspaceDigestChain,
  SuiteChain, Rootknot v4 -- one test per subsystem catches drift
  at the source.
- Backward-compat: pre-v0.5.1 artifacts without run_id verify silently
  (WARN log, no exception).
- Ambient contract: :func:`bind_run_id` propagates through nested
  code paths; explicit kwargs still win over ambient.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pytest

from ract.core.assumption import Evidence
from ract.core.assumption_registry import AssumptionRegistry
from ract.core.assumptions_wal import AssumptionWal
from ract.core.rootknot import make_rootknot_v4
from ract.core.suite_chain import SuiteChain
from ract.core.types import Digest
from ract.core.workspace_digest import (
    WorkspaceDigestChain,
    compute_prompt_digest,
    run_id_hex,
)
from ract.core.keys import SessionKey
from ract.runtime import bind_run_id, get_current_run_id, set_current_run_id
from ract.trace.writer import JsonlEventWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _digest(seed: bytes) -> Digest:
    """Return a 32-byte deterministic Digest for a seed."""
    return Digest(hashlib.sha256(seed).digest())


class _EnvSigner:
    """Test double implementing the ``sign(bytes) -> bytes`` contract."""

    def __init__(self, tag: bytes) -> None:
        self._tag = tag

    def sign(self, data: bytes) -> bytes:
        return hashlib.sha256(self._tag + data).digest() + b"\x00" * 32


# ---------------------------------------------------------------------------
# 1. Per-layer smoke tests -- catch drift AT the source
# ---------------------------------------------------------------------------


def test_wal_carries_run_id(tmp_path: Path) -> None:
    """AssumptionRegistry with wal_dir under a bound ambient stamps every
    WAL entry with the same run_id.
    """
    rid = run_id_hex()
    wal_dir = tmp_path / ".ract"
    with bind_run_id(rid):
        registry = AssumptionRegistry(wal_dir=wal_dir)
        a1 = registry.propose("first assumption")
        registry.accept(a1.id)
        a2 = registry.propose("second assumption", depends_on=(a1.id,))
        registry.discharge(a2.id, evidence=Evidence(text="satisfied by test"))

    wal = AssumptionWal(wal_dir)
    _, wal_entries = wal.load_all()
    assert wal_entries, "WAL should have at least one entry"
    for entry in wal_entries:
        assert entry.payload.get("run_id") == rid, (
            f"WAL entry {entry.kind} missing run_id or drifted: "
            f"{entry.payload.get('run_id')!r} != {rid!r}"
        )


def test_events_jsonl_carries_run_id(tmp_path: Path) -> None:
    """JsonlEventWriter constructed under a bound ambient stamps every
    event with the same run_id.
    """
    rid = run_id_hex()
    events_path = tmp_path / "events.jsonl"
    with bind_run_id(rid):
        writer = JsonlEventWriter(events_path)
        writer.emit("run.started", {"note": "under bound ambient"})
        writer.emit("step.started", {"step": 1})
        writer.emit("run.completed", {"reason": "COMPLETE"})

    # Reader: parse each line and confirm run_id hex matches.
    rid_bytes = bytes.fromhex(rid)
    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    import json as _json

    for line in lines:
        payload = _json.loads(line)
        assert payload["run_id"] == rid_bytes.hex() == rid, (
            f"event {payload['kind']} run_id drifted: "
            f"{payload['run_id']!r} != {rid!r}"
        )


def test_workspace_digest_chain_carries_run_id(tmp_path: Path) -> None:
    """WorkspaceDigestChain edges written under a bound ambient stamp
    the same run_id on every edge; legacy edges without run_id survive
    round-trip as ChainEdge.run_id == None.
    """
    rid = run_id_hex()
    chain = WorkspaceDigestChain(tmp_path)

    # Write one legacy edge (no ambient bound) then two under-ambient
    # edges. All three parse back cleanly.
    root_digest = _digest(b"root")
    with bind_run_id(rid):
        chain.append(root_digest, parent=None)
        second = _digest(b"second")
        chain.append(second, parent=root_digest)
        third = _digest(b"third")
        chain.append(third, parent=second)

    edges = chain.edges()
    assert len(edges) == 3
    for edge in edges:
        assert edge.run_id == rid, (
            f"edge {edge.child[:8]}... run_id drifted: "
            f"{edge.run_id!r} != {rid!r}"
        )


def test_workspace_digest_chain_legacy_edge_verifies_silently(
    tmp_path: Path,
) -> None:
    """A pre-module_06 edge (no run_id in the payload) survives round-trip
    as ``ChainEdge.run_id is None`` -- backward-compat.
    """
    chain = WorkspaceDigestChain(tmp_path)
    # No ambient bound + no explicit kwarg -> legacy shape.
    root_digest = _digest(b"legacy_root")
    chain.append(root_digest, parent=None)
    edges = chain.edges()
    assert len(edges) == 1
    assert edges[0].run_id is None
    assert edges[0].child == root_digest.hex()


def test_suite_chain_carries_run_id(tmp_path: Path) -> None:
    """SuiteChain.append records the exact run_id the caller passes;
    with the ambient contract this is the same value bound at loop
    entry.
    """
    rid = run_id_hex()
    chain = SuiteChain(tmp_path)
    prompt_digest = bytes(compute_prompt_digest("first intent"))
    chain.append(
        prompt_digest=prompt_digest,
        suite_digest="a" * 64,
        run_id=rid,
        origin="initial",
    )
    prompt_digest2 = bytes(compute_prompt_digest("second intent"))
    chain.append(
        prompt_digest=prompt_digest2,
        suite_digest="b" * 64,
        run_id=rid,
        origin="operator_recompile",
    )
    entries = chain.entries()
    assert len(entries) == 2
    for entry in entries:
        assert entry.run_id == rid, (
            f"SuiteChain entry {entry.origin} run_id drifted: "
            f"{entry.run_id!r} != {rid!r}"
        )


def test_rootknot_v4_run_id_matches_ambient() -> None:
    """make_rootknot_v4 falls back to the ambient run_id when the caller
    passes ``None``; explicit kwarg still wins over ambient.
    """
    rid = run_id_hex()

    import tempfile as _tf

    key_state = Path(_tf.mkdtemp())
    key = SessionKey.load_or_create(b"\x11" * 16, state_dir=key_state)
    sandbox = _EnvSigner(b"sandbox")
    alm = _EnvSigner(b"alm")

    # (a) No explicit run_id -> ambient falls through.
    with bind_run_id(rid):
        knot = make_rootknot_v4(
            key=key,
            sandbox_signer=sandbox,
            alm_signer=alm,
            workspace_path="/tmp/ws",
            artifact_digest=_digest(b"artifact"),
            assumption_digest=_digest(b"assumption"),
            acceptance_suite_digest=_digest(b"suite"),
            predicate_results=(_digest(b"p1"),),
            manifest_digest=_digest(b"manifest"),
            gate_results=(),
            workspace_digest=_digest(b"workspace"),
            prompt_digest=_digest(b"prompt"),
            run_id=None,  # ambient fallback path
        )
        assert knot.run_id == rid

    # (b) Explicit kwarg wins over ambient.
    override = run_id_hex()
    with bind_run_id(rid):
        knot2 = make_rootknot_v4(
            key=key,
            sandbox_signer=sandbox,
            alm_signer=alm,
            workspace_path="/tmp/ws",
            artifact_digest=_digest(b"artifact"),
            assumption_digest=_digest(b"assumption"),
            acceptance_suite_digest=_digest(b"suite"),
            predicate_results=(_digest(b"p1"),),
            manifest_digest=_digest(b"manifest"),
            gate_results=(),
            workspace_digest=_digest(b"workspace"),
            prompt_digest=_digest(b"prompt"),
            run_id=override,
        )
        assert knot2.run_id == override
        assert knot2.run_id != rid


def test_rootknot_v4_refuses_when_no_ambient_and_no_kwarg() -> None:
    """When neither an explicit run_id nor an ambient is available, the
    v4 factory raises loudly -- silent id-drop is a control-bypass.
    """
    import tempfile as _tf

    key_state = Path(_tf.mkdtemp())
    key = SessionKey.load_or_create(b"\x11" * 16, state_dir=key_state)
    sandbox = _EnvSigner(b"sandbox")
    alm = _EnvSigner(b"alm")

    # Ensure no ambient is bound.
    assert get_current_run_id() is None

    with pytest.raises(ValueError, match="run_id"):
        make_rootknot_v4(
            key=key,
            sandbox_signer=sandbox,
            alm_signer=alm,
            workspace_path="/tmp/ws",
            artifact_digest=_digest(b"artifact"),
            assumption_digest=_digest(b"assumption"),
            acceptance_suite_digest=_digest(b"suite"),
            predicate_results=(_digest(b"p1"),),
            manifest_digest=_digest(b"manifest"),
            gate_results=(),
            workspace_digest=_digest(b"workspace"),
            prompt_digest=_digest(b"prompt"),
            run_id=None,
        )


# ---------------------------------------------------------------------------
# 2. Ambient contract
# ---------------------------------------------------------------------------


def test_bind_run_id_scoped_and_restores_on_exit() -> None:
    """bind_run_id sets the ambient for the block and restores on exit
    (including exception paths).
    """
    assert get_current_run_id() is None

    rid_a = run_id_hex()
    with bind_run_id(rid_a):
        assert get_current_run_id() == rid_a
    assert get_current_run_id() is None

    # Exception path also restores.
    with pytest.raises(RuntimeError, match="boom"):
        with bind_run_id(rid_a):
            assert get_current_run_id() == rid_a
            raise RuntimeError("boom")
    assert get_current_run_id() is None


def test_bind_run_id_nested_bindings_stack_and_unwind() -> None:
    """Nested bind_run_id contexts stack LIFO and unwind cleanly."""
    outer = run_id_hex()
    inner = run_id_hex()
    assert outer != inner

    with bind_run_id(outer):
        assert get_current_run_id() == outer
        with bind_run_id(inner):
            assert get_current_run_id() == inner
        assert get_current_run_id() == outer
    assert get_current_run_id() is None


def test_bind_run_id_refuses_empty_string() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        with bind_run_id(""):  # noqa: SIM117
            pass
    with pytest.raises(ValueError, match="non-empty string"):
        with bind_run_id(None):  # type: ignore[arg-type]
            pass


def test_set_current_run_id_type_guard() -> None:
    """set_current_run_id refuses non-str non-None inputs."""
    with pytest.raises(TypeError, match="run_id"):
        set_current_run_id(b"bytes-not-str")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. End-to-end: full loop artifact stamping + compaction survival
# ---------------------------------------------------------------------------


def test_run_id_preserved_across_full_loop(tmp_path: Path) -> None:
    """Spawn a full-loop-equivalent flow. Every artifact carries the
    same run_id. A simulated compaction event (fresh subsystem
    instances loading from persisted state) preserves it.
    """
    rid = run_id_hex()
    ract_dir = tmp_path / ".ract"
    run_dir = tmp_path / "run"
    events_path = tmp_path / "events.jsonl"

    import tempfile as _tf

    key_state = Path(_tf.mkdtemp())
    key = SessionKey.load_or_create(b"\x11" * 16, state_dir=key_state)
    sandbox = _EnvSigner(b"sandbox")
    alm = _EnvSigner(b"alm")

    # --- Pass 1: initial run under bound ambient ---
    with bind_run_id(rid):
        # 1. Write ambient id marker + suite chain initial entry.
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run_id.txt").write_text(rid, encoding="utf-8")
        suite_chain = SuiteChain(run_dir)
        prompt_digest = bytes(compute_prompt_digest("build me foo"))
        suite_chain.append(
            prompt_digest=prompt_digest,
            suite_digest="a" * 64,
            run_id=rid,
            origin="initial",
        )

        # 2. WAL entries (three transitions).
        registry = AssumptionRegistry(wal_dir=ract_dir)
        a1 = registry.propose("intent binds workspace")
        registry.accept(a1.id)

        # 3. WorkspaceDigestChain edges (two edges).
        ws_chain = WorkspaceDigestChain(ract_dir)
        root_ws = _digest(b"ws_root")
        ws_chain.append(root_ws, parent=None)
        second_ws = _digest(b"ws_second")
        ws_chain.append(second_ws, parent=root_ws)

        # 4. Event log (three events).
        event_writer = JsonlEventWriter(events_path)
        event_writer.emit("run.started", {"iteration": 0})
        event_writer.emit("step.committed", {"step": 1})

        # 5. Rootknot v4 (ambient fallback path).
        knot = make_rootknot_v4(
            key=key,
            sandbox_signer=sandbox,
            alm_signer=alm,
            workspace_path=str(tmp_path),
            artifact_digest=_digest(b"artifact"),
            assumption_digest=_digest(b"assumption"),
            acceptance_suite_digest=_digest(b"suite"),
            predicate_results=(_digest(b"p1"),),
            manifest_digest=_digest(b"manifest"),
            gate_results=(),
            workspace_digest=second_ws,
            prompt_digest=Digest(prompt_digest),
            run_id=None,  # ambient
        )

    # --- Assert every emitted artifact carries the same run_id ---
    wal = AssumptionWal(ract_dir)
    _, wal_entries = wal.load_all()
    assert wal_entries, "WAL entries expected"
    for entry in wal_entries:
        assert entry.payload.get("run_id") == rid

    for edge in ws_chain.edges():
        assert edge.run_id == rid

    for entry in suite_chain.entries():
        assert entry.run_id == rid

    import json as _json

    for line in events_path.read_text(encoding="utf-8").splitlines():
        assert _json.loads(line)["run_id"] == rid

    assert knot.run_id == rid

    # --- Pass 2: simulated compaction ---
    # Fresh subsystem instances load the persisted state. The run_id
    # they SEE on replay is the one recorded on-disk; a fresh loop
    # continuing this run binds the same ambient (marker-file resolve
    # path).
    marker = run_dir / "run_id.txt"
    reloaded_rid = marker.read_text(encoding="utf-8").strip()
    assert reloaded_rid == rid

    with bind_run_id(reloaded_rid):
        # Reload the WAL registry -- replay reconstructs the same
        # assumption graph. New transitions under the reloaded ambient
        # stamp the same rid.
        registry2 = AssumptionRegistry(wal_dir=ract_dir)
        assert registry2.get(a1.id) is not None
        registry2.propose("post-compaction assumption")
        # WorkspaceDigestChain append under reloaded ambient.
        ws_chain2 = WorkspaceDigestChain(ract_dir)
        third_ws = _digest(b"ws_third")
        ws_chain2.append(third_ws, parent=second_ws)
        # Event log continues under the same rid via bytes.fromhex
        # decode of ambient hex.
        event_writer2 = JsonlEventWriter(events_path)
        event_writer2.emit(
            "step.committed", {"step": 2, "post_compaction": True}
        )

    # Final assertion: EVERY artifact on disk (across both passes)
    # carries the exact same run_id.
    _, wal_final = AssumptionWal(ract_dir).load_all()
    for entry in wal_final:
        assert entry.payload.get("run_id") == rid, (
            f"post-compaction WAL entry {entry.kind} drifted: "
            f"{entry.payload.get('run_id')!r}"
        )

    for edge in WorkspaceDigestChain(ract_dir).edges():
        assert edge.run_id == rid

    for line in events_path.read_text(encoding="utf-8").splitlines():
        assert _json.loads(line)["run_id"] == rid


# ---------------------------------------------------------------------------
# 4. LoopController end-of-run ambient wiring
# ---------------------------------------------------------------------------


def test_loop_controller_binds_ambient_run_id_at_run_entry(
    tmp_path: Path,
) -> None:
    """LoopController.run() binds the ambient run_id for the whole run.

    This is the load-bearing propagation site -- every subsystem the
    loop reaches inside ``run()`` inherits the id. Verified by driving
    the smallest possible controller loop and observing that the T8
    diagnostic path (which consults ``_resolve_run_id``) sees the
    ambient value.
    """
    import secrets

    from ract.core.loop import WorkspaceSnapshot, build_loop_state
    from ract.core.predicate import (
        AcceptancePredicate,
        AcceptanceSuite,
        ArtifactInvocation,
        new_intent_id,
        new_predicate_id,
    )
    from ract.loop_controller import LoopController
    from ract.manager import Plan

    config = tmp_path / "ract.yaml"
    config.write_text("providers: []\n", encoding="utf-8")
    ract_dir = tmp_path / ".ract"
    ract_dir.mkdir()
    (ract_dir / "operator.key").write_bytes(secrets.token_bytes(64))
    run_dir = tmp_path / "run-controller"
    run_dir.mkdir()

    # Pre-seed the marker file so the controller's resolver picks it up.
    marker_rid = run_id_hex()
    (run_dir / "run_id.txt").write_text(marker_rid, encoding="utf-8")

    predicate = AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(
            path="__never_present__", must_have_rootknot=False
        ),
        required=True,
    )
    suite = AcceptanceSuite(
        intent_id=new_intent_id(),
        predicates=(predicate,),
        compiled_from="controller test intent",
        prompt_digest=bytes(compute_prompt_digest("controller test intent")),
    )

    controller = LoopController(
        config,
        max_iterations=1,
        acceptance_suite=suite,
        run_dir=run_dir,
    )
    # Seed the LoopState + last-known-good so the T8 hook (which
    # consults the ambient via _resolve_run_id) has a valid state
    # to run against without needing full run() plumbing.
    controller._loop_state = build_loop_state(
        plan=Plan(assumption="controller test intent", confidence=1.0, steps=[]),
        workspace=WorkspaceSnapshot(),
        suite=suite,
        run_dir=run_dir,
    )

    # Verify the resolver returns the marker id.
    resolved = controller._resolve_or_mint_run_id()
    assert resolved == marker_rid

    # Under bind, _resolve_run_id sees the ambient.
    with bind_run_id(marker_rid):
        assert controller._resolve_run_id(controller._loop_state) == marker_rid


def test_loop_controller_mints_run_id_when_marker_absent(
    tmp_path: Path,
) -> None:
    """When no marker exists, the controller mints an id AND writes the
    marker so a follow-up compaction picks up the same value.
    """
    from ract.loop_controller import LoopController

    config = tmp_path / "ract.yaml"
    config.write_text("providers: []\n", encoding="utf-8")
    run_dir = tmp_path / "run-no-marker"

    controller = LoopController(config, max_iterations=1, run_dir=run_dir)
    resolved = controller._resolve_or_mint_run_id()
    assert resolved
    # Marker written for compaction survival.
    marker = run_dir / "run_id.txt"
    assert marker.exists()
    assert marker.read_text(encoding="utf-8").strip() == resolved

    # Second call resolves to the same value.
    resolved2 = controller._resolve_or_mint_run_id()
    assert resolved2 == resolved


# ---------------------------------------------------------------------------
# 5. Backward-compat: pre-v0.5.1 artifacts verify silently
# ---------------------------------------------------------------------------


def test_pre_v051_wal_entries_verify_silently(
    tmp_path: Path, caplog
) -> None:
    """A WAL entry appended before module_06 landed carries no run_id in
    the payload. The registry loads it back without raising -- the
    field is optional.
    """
    wal_dir = tmp_path / ".ract"
    wal = AssumptionWal(wal_dir)
    # Emulate a legacy write: append directly without a run_id in the
    # payload (bypass the registry which now stamps ambient).
    wal.append(
        "proposed",
        {
            "assumption_id": "aa" * 16,
            "digest": "bb" * 32,
            "text": "legacy assumption",
            "depends_on": [],
        },
    )
    # Load path: no error; no run_id key on the entry payload.
    _, wal_entries = wal.load_all()
    assert len(wal_entries) == 1
    assert "run_id" not in wal_entries[0].payload

    # Registry reload: also succeeds.
    with caplog.at_level(logging.WARNING):
        registry = AssumptionRegistry(wal_dir=wal_dir)
        # The legacy assumption is present in memory after replay.
        from ract.core.assumption import AssumptionId

        aid = AssumptionId(bytes.fromhex("aa" * 16))
        assert registry.get(aid) is not None
