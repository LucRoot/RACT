"""Tests for ALM Invariant AL-1 + sycophancy circuit + Investigator.

ALM module_05. 10 baseline tests cover the three sub-clauses of AL-1
(signature verify, gate-results pass or handshake, reversal-taint clean
or accepted), the v1/v2/v3 sidecar dispatch, the sycophancy scanner's
forcing-prompt path, and the Investigator's report-required contract.
"""

from __future__ import annotations

import tempfile
import uuid
import warnings
from pathlib import Path

import pytest

from ract.antilazy.investigator import (
    InvestigatorFinding,
    emit_investigator_missing_event,
    run_investigator,
    select_investigation_files,
)
from ract.antilazy.symgraph import (
    CallEdge,
    ImportEdge,
    SymbolGraph,
    SymbolNode,
)
from ract.antilazy.sycophancy import (
    _classify_position,
    force_evidence_or_restore,
    scan_trace,
    taint_run,
)
from ract.core.keys import SessionKey
from ract.core.provenance import (
    ProvenanceIndex,
    _knot_from_json,
    verify_workspace,
)
from ract.core.rootknot import (
    GateResult,
    Rootknot,
    make_rootknot,
    make_rootknot_v2,
    make_rootknot_v3,
)
from ract.core.types import Digest, digest_bytes
from ract.security.alm_verifier_key import AlmVerifierKey
from ract.security.keys import SandboxKey
from ract.trace.events import Event, EventChain


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_key() -> SessionKey:
    return SessionKey.load_or_create(b"\x00" * 16)


@pytest.fixture
def fresh_workspace() -> Path:  # type: ignore[misc]
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _assumption_registry(assumption_digest: Digest) -> dict:
    return {
        assumption_digest: type(
            "A", (), {"state": type("S", (), {"name": "ACTIVE"})()}
        )()
    }


def _sample_v3(
    session_key: SessionKey,
    sandbox_key: SandboxKey,
    alm_key: AlmVerifierKey,
    workspace: Path,
    content: bytes,
    *,
    gate_results: tuple[GateResult, ...] | None = None,
    reversal_taint: str = "clean",
) -> tuple[Rootknot, Digest, Digest]:
    """Build a v3 rootknot for ``workspace/artifact.txt``."""
    artifact = workspace / "artifact.txt"
    artifact.write_bytes(content)
    suite_digest = digest_bytes(b"suite-canonical-v3")
    manifest_digest = digest_bytes(b"manifest-canonical-v3")
    predicate_results = (digest_bytes(b"pred-v3-result"),)
    grs = (
        gate_results
        if gate_results is not None
        else tuple(
            GateResult(gate_id=f"G{i}", passed=True, evidence_digest=digest_bytes(f"g{i}".encode()))
            for i in range(1, 9)
        )
    )
    knot = make_rootknot_v3(
        key=session_key,
        sandbox_signer=sandbox_key,
        alm_signer=alm_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(content),
        assumption_digest=digest_bytes(b"assume-v3"),
        acceptance_suite_digest=suite_digest,
        predicate_results=predicate_results,
        manifest_digest=manifest_digest,
        gate_results=grs,
        reversal_taint=reversal_taint,  # type: ignore[arg-type]
    )
    return knot, suite_digest, manifest_digest


# ---------------------------------------------------------------------------
# Test 1 — AL-1.1 signature verifies under ALM pubkey
# ---------------------------------------------------------------------------


def test_antilazy_signature_verifies_under_alm_pubkey(
    fresh_workspace: Path, session_key: SessionKey
) -> None:
    sandbox_key = SandboxKey.generate(b"\x10" * 16, workspace_root=fresh_workspace)
    alm_key = AlmVerifierKey.generate(b"\x11" * 16, workspace_root=fresh_workspace)
    knot, _suite, _manifest = _sample_v3(
        session_key, sandbox_key, alm_key, fresh_workspace, b"al1-payload"
    )
    # Positive case: the correct pubkey verifies.
    assert knot.verify_antilazy(alm_key.public)

    # Negative case: a bit-flip in the signature must fail verify.
    flipped_sig = bytes([knot.antilazy_signature[0] ^ 0xFF]) + knot.antilazy_signature[1:]
    forged = Rootknot(
        plan_id=knot.plan_id,
        step_id=knot.step_id,
        assumption_digest=knot.assumption_digest,
        generator=knot.generator,
        parent_digests=knot.parent_digests,
        workspace_path=knot.workspace_path,
        artifact_digest=knot.artifact_digest,
        created_at_ns=knot.created_at_ns,
        generator_signature=knot.generator_signature,
        environment_signature=knot.environment_signature,
        acceptance_suite_digest=knot.acceptance_suite_digest,
        predicate_results=knot.predicate_results,
        manifest_digest=knot.manifest_digest,
        antilazy_signature=flipped_sig,
        gate_results=knot.gate_results,
        reversal_taint=knot.reversal_taint,
        schema_version=3,
    )
    assert not forged.verify_antilazy(alm_key.public)


# ---------------------------------------------------------------------------
# Test 2 — AL-1.2 all gates pass -> AL-1 holds
# ---------------------------------------------------------------------------


def test_gate_results_all_pass_al1_holds(
    fresh_workspace: Path, session_key: SessionKey
) -> None:
    sandbox_key = SandboxKey.generate(b"\x12" * 16, workspace_root=fresh_workspace)
    alm_key = AlmVerifierKey.generate(b"\x13" * 16, workspace_root=fresh_workspace)
    knot, suite_digest, manifest_digest = _sample_v3(
        session_key, sandbox_key, alm_key, fresh_workspace, b"al1-2-payload"
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(
        knot,
        fresh_workspace / "artifact.txt",
        sandbox_pubkey=sandbox_key.public,
        alm_pubkey=alm_key.public,
    )

    result = verify_workspace(
        index,
        active_plans={knot.plan_id: [knot.step_id]},
        registered_assumptions=_assumption_registry(knot.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        sandbox_pubkey=lambda _k: sandbox_key.public,
        alm_pubkey=lambda _k: alm_key.public,
        registered_suites={suite_digest},
        registered_manifests={manifest_digest},
        strict=True,
    )
    assert result.is_ok(), result.unwrap_err()


# ---------------------------------------------------------------------------
# Test 3 — AL-1.2 G2 fail without handshake -> AL-1 fails
# ---------------------------------------------------------------------------


def test_gate_result_fail_without_handshake_al1_fails(
    fresh_workspace: Path, session_key: SessionKey
) -> None:
    sandbox_key = SandboxKey.generate(b"\x14" * 16, workspace_root=fresh_workspace)
    alm_key = AlmVerifierKey.generate(b"\x15" * 16, workspace_root=fresh_workspace)
    grs = tuple(
        GateResult(gate_id=f"G{i}", passed=(i != 2), evidence_digest=digest_bytes(f"g{i}".encode()))
        for i in range(1, 9)
    )
    knot, suite_digest, manifest_digest = _sample_v3(
        session_key,
        sandbox_key,
        alm_key,
        fresh_workspace,
        b"al1-3-payload",
        gate_results=grs,
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(
        knot,
        fresh_workspace / "artifact.txt",
        sandbox_pubkey=sandbox_key.public,
        alm_pubkey=alm_key.public,
    )

    result = verify_workspace(
        index,
        active_plans={knot.plan_id: [knot.step_id]},
        registered_assumptions=_assumption_registry(knot.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        sandbox_pubkey=lambda _k: sandbox_key.public,
        alm_pubkey=lambda _k: alm_key.public,
        registered_suites={suite_digest},
        registered_manifests={manifest_digest},
        strict=True,
    )
    assert not result.is_ok()
    violation = result.unwrap_err()
    assert violation.predicate == "AL-1.2"
    assert "G2" in violation.detail


# ---------------------------------------------------------------------------
# Test 4 — AL-1.3 partial taint without handshake -> AL-1 fails
# ---------------------------------------------------------------------------


def test_reversal_taint_partial_without_handshake_al1_fails(
    fresh_workspace: Path, session_key: SessionKey
) -> None:
    sandbox_key = SandboxKey.generate(b"\x16" * 16, workspace_root=fresh_workspace)
    alm_key = AlmVerifierKey.generate(b"\x17" * 16, workspace_root=fresh_workspace)
    knot, suite_digest, manifest_digest = _sample_v3(
        session_key,
        sandbox_key,
        alm_key,
        fresh_workspace,
        b"al1-4-payload",
        reversal_taint="partial",
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(
        knot,
        fresh_workspace / "artifact.txt",
        sandbox_pubkey=sandbox_key.public,
        alm_pubkey=alm_key.public,
    )

    result = verify_workspace(
        index,
        active_plans={knot.plan_id: [knot.step_id]},
        registered_assumptions=_assumption_registry(knot.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        sandbox_pubkey=lambda _k: sandbox_key.public,
        alm_pubkey=lambda _k: alm_key.public,
        registered_suites={suite_digest},
        registered_manifests={manifest_digest},
        strict=True,
    )
    assert not result.is_ok()
    assert result.unwrap_err().predicate == "AL-1.3"


# ---------------------------------------------------------------------------
# Test 5 — AL-1.3 partial taint WITH handshake -> AL-1 passes
# ---------------------------------------------------------------------------


def test_reversal_taint_partial_with_operator_handshake_al1_passes(
    fresh_workspace: Path, session_key: SessionKey
) -> None:
    sandbox_key = SandboxKey.generate(b"\x18" * 16, workspace_root=fresh_workspace)
    alm_key = AlmVerifierKey.generate(b"\x19" * 16, workspace_root=fresh_workspace)
    knot, suite_digest, manifest_digest = _sample_v3(
        session_key,
        sandbox_key,
        alm_key,
        fresh_workspace,
        b"al1-5-payload",
        reversal_taint="partial",
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(
        knot,
        fresh_workspace / "artifact.txt",
        sandbox_pubkey=sandbox_key.public,
        alm_pubkey=alm_key.public,
    )

    result = verify_workspace(
        index,
        active_plans={knot.plan_id: [knot.step_id]},
        registered_assumptions=_assumption_registry(knot.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        sandbox_pubkey=lambda _k: sandbox_key.public,
        alm_pubkey=lambda _k: alm_key.public,
        registered_suites={suite_digest},
        registered_manifests={manifest_digest},
        accepted_partial_taint_runs={knot.plan_id},
        strict=True,
    )
    assert result.is_ok(), result.unwrap_err()


# ---------------------------------------------------------------------------
# Test 6 — v1 sidecar verifies RK-1/RK-2 only, AL-1 skipped
# ---------------------------------------------------------------------------


def test_sidecar_v1_verifies_rk1_rk2_only_al1_skipped(
    fresh_workspace: Path, session_key: SessionKey
) -> None:
    artifact = fresh_workspace / "artifact.txt"
    artifact.write_bytes(b"v1-payload")
    knot = make_rootknot(
        key=session_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"v1-payload"),
        assumption_digest=digest_bytes(b"assume-v1"),
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(knot, artifact)

    with warnings.catch_warnings():
        warnings.simplefilter("always")
        result = verify_workspace(
            index,
            active_plans={knot.plan_id: [knot.step_id]},
            registered_assumptions=_assumption_registry(knot.assumption_digest),
            generator_pubkey=lambda _g: session_key.public_key_bytes(),
        )
    assert result.is_ok(), result.unwrap_err()

    # strict mode refuses v1 outright (it fails RK-3 first — the earliest
    # bar the strict path checks).
    result_strict = verify_workspace(
        index,
        active_plans={knot.plan_id: [knot.step_id]},
        registered_assumptions=_assumption_registry(knot.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        strict=True,
    )
    assert not result_strict.is_ok()
    # Either RK-3 or AL-1 is the first strict refusal; either is
    # correct since both fail for a v1 sidecar.
    assert result_strict.unwrap_err().predicate in ("RK-3", "AL-1")


# ---------------------------------------------------------------------------
# Test 7 — v3 sidecar embeds ALM pubkey, offline verify works
# ---------------------------------------------------------------------------


def test_sidecar_v3_embeds_alm_pubkey_offline_verify_works(
    fresh_workspace: Path, session_key: SessionKey
) -> None:
    sandbox_key = SandboxKey.generate(b"\x1a" * 16, workspace_root=fresh_workspace)
    alm_key = AlmVerifierKey.generate(b"\x1b" * 16, workspace_root=fresh_workspace)
    knot, _s, _m = _sample_v3(
        session_key, sandbox_key, alm_key, fresh_workspace, b"al1-7-payload"
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(
        knot,
        fresh_workspace / "artifact.txt",
        sandbox_pubkey=sandbox_key.public,
        alm_pubkey=alm_key.public,
    )

    embedded = index.load_sidecar_alm_pubkey(fresh_workspace / "artifact.txt")
    assert embedded == alm_key.public

    # Offline verify: reconstruct the knot from disk, verify with the
    # embedded pubkey alone (no key store consulted).
    sidecar = fresh_workspace / ".artifact.txt.rootknot.json"
    reloaded = _knot_from_json(sidecar.read_text(encoding="utf-8"))
    assert reloaded.verify_antilazy(embedded)


# ---------------------------------------------------------------------------
# Test 8 — Investigator report required for completion
# ---------------------------------------------------------------------------


def test_investigator_report_required_for_completion(
    fresh_workspace: Path,
) -> None:
    events: list[dict] = []

    def _capture(kind: str, payload: dict) -> None:
        events.append({"kind": kind, "payload": payload})

    # Monkey-patch the sink for this test.
    from ract.trace import sink

    original = sink.emit
    sink.emit = _capture  # type: ignore[assignment]
    try:
        emit_investigator_missing_event()
    finally:
        sink.emit = original  # type: ignore[assignment]

    assert any(
        e["kind"] == "laziness.violated"
        and e["payload"].get("kind") == "investigator_missing"
        for e in events
    )


# ---------------------------------------------------------------------------
# Test 9 — Investigator finding of kind missed_call_site_update
# ---------------------------------------------------------------------------


def test_investigator_finding_feeds_g6_uncovered() -> None:
    # Build a tiny SymbolGraph: two files, one calls the other.
    symbols = {
        "app.core.f": SymbolNode(
            qualified_name="app.core.f",
            source_file="app/core.py",
            start_line=1,
            end_line=5,
            kind="function",
        ),
        "app.consumer.uses_f": SymbolNode(
            qualified_name="app.consumer.uses_f",
            source_file="app/consumer.py",
            start_line=1,
            end_line=3,
            kind="function",
        ),
    }
    calls = (
        CallEdge(
            caller="app.consumer.uses_f",
            callee="app.core.f",
            source_file="app/consumer.py",
            line=2,
        ),
    )
    imports = (
        ImportEdge(
            importer="app.consumer",
            imported_name="app.core.f",
            source_file="app/consumer.py",
            line=1,
        ),
    )
    graph = SymbolGraph(
        symbols=symbols, call_edges=calls, import_edges=imports
    )

    touched = (Path("app/core.py"),)
    selected = select_investigation_files(graph, touched, max_files=5)
    # consumer.py is untouched and adjacent to core.py via both call and
    # import edges — it must appear in the selection.
    assert Path("app/consumer.py") in selected

    # Probe: return a missed_call_site_update finding for consumer.py.
    def probe(intent: str, path: Path, contents: str):
        return InvestigatorFinding(
            file=path,
            line=2,
            kind="missed_call_site_update",
            evidence="f() renamed but this caller still uses the old name",
        )

    def reader(_p: Path) -> str:
        return "irrelevant contents"

    run_id = uuid.uuid4().bytes
    report = run_investigator(
        intent="rename core.f to core.g",
        symgraph=graph,
        touched_files=touched,
        probe=probe,
        file_reader=reader,
        run_id=run_id,
        max_files=5,
    )
    assert report.findings
    kinds = {f.kind for f in report.findings}
    assert "missed_call_site_update" in kinds
    # The report's files_read must equal the union of finding files +
    # explicit-no-finding files.
    read_set = set(report.files_read)
    finding_set = {f.file for f in report.findings}
    assert (finding_set | set(report.no_finding_explicit)) == read_set


# ---------------------------------------------------------------------------
# Test 10 — Suspicious reversal fires forcing prompt
# ---------------------------------------------------------------------------


def _mk_event(chain: EventChain, kind: str, payload: dict) -> Event:
    ev = chain.build_next(kind=kind, payload=payload)
    chain.append(ev)
    return ev


def test_suspicious_reversal_no_new_evidence_forces_prompt() -> None:
    run_id = uuid.uuid4().bytes
    chain = EventChain(run_id=run_id)
    _mk_event(
        chain,
        "response.received",
        {"role": "primary", "assistant_text": "The fix is complete and correct."},
    )
    _mk_event(
        chain,
        "response.received",
        {"role": "primary", "assistant_text": "Actually the fix is wrong, reverting."},
    )
    reports = scan_trace(chain.events)
    assert reports
    assert any(r.is_suspicious for r in reports)

    # Forcing prompt attaches to a stub loop.
    class _StubLoop:
        _repair_intent: str | None = None

    stub = _StubLoop()
    force_evidence_or_restore(reports[0], stub)
    assert stub._repair_intent is not None
    assert "REVERSAL CHALLENGE" in stub._repair_intent

    # taint_run: partial when suspicious.
    assert taint_run(reports, operator_accepted=False) == "partial"
    # Operator acceptance still records taint (verifier handshake path
    # is what lifts it, not the taint value).
    assert taint_run(reports, operator_accepted=True) == "partial"


# ---------------------------------------------------------------------------
# Test 11 — Suspicious reversal absorbed by intervening evidence
# ---------------------------------------------------------------------------


def test_reversal_absorbed_by_intervening_evidence() -> None:
    """Bonus coverage: an evidence event between the two turns lifts is_suspicious."""
    run_id = uuid.uuid4().bytes
    chain = EventChain(run_id=run_id)
    _mk_event(
        chain,
        "response.received",
        {"role": "primary", "assistant_text": "The fix is complete."},
    )
    _mk_event(
        chain,
        "tool.result",
        {"tool": "pytest", "outcome": "3 tests failed"},
    )
    _mk_event(
        chain,
        "response.received",
        {"role": "primary", "assistant_text": "You are right, the fix is broken."},
    )
    reports = scan_trace(chain.events)
    assert reports
    # The evidence event landed between turn 1 and turn 3; suspicion clears.
    assert all(not r.is_suspicious for r in reports)


# ---------------------------------------------------------------------------
# Test 12 — v2 sidecars keep verifying under the new reader path
# ---------------------------------------------------------------------------


def test_v2_sidecar_backwards_compat(
    fresh_workspace: Path, session_key: SessionKey
) -> None:
    """AL-1 skips for v2 sidecars but RK-1/2/3 still verifies."""
    sandbox_key = SandboxKey.generate(b"\x1c" * 16, workspace_root=fresh_workspace)
    artifact = fresh_workspace / "artifact.txt"
    artifact.write_bytes(b"v2-payload")
    suite_digest = digest_bytes(b"suite-canonical-v2")
    manifest_digest = digest_bytes(b"manifest-canonical-v2")
    predicate_results = (digest_bytes(b"pred-v2-result"),)
    knot = make_rootknot_v2(
        key=session_key,
        sandbox_signer=sandbox_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"v2-payload"),
        assumption_digest=digest_bytes(b"assume-v2-compat"),
        acceptance_suite_digest=suite_digest,
        predicate_results=predicate_results,
        manifest_digest=manifest_digest,
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(knot, artifact, sandbox_pubkey=sandbox_key.public)

    # Non-strict: AL-1 skips with a DeprecationWarning; RK-3 passes.
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        result = verify_workspace(
            index,
            active_plans={knot.plan_id: [knot.step_id]},
            registered_assumptions=_assumption_registry(knot.assumption_digest),
            generator_pubkey=lambda _g: session_key.public_key_bytes(),
            sandbox_pubkey=lambda _k: sandbox_key.public,
            registered_suites={suite_digest},
            registered_manifests={manifest_digest},
        )
    assert result.is_ok(), result.unwrap_err()

    # Strict: v2 must be refused with AL-1 (module_05 raises the bar).
    result_strict = verify_workspace(
        index,
        active_plans={knot.plan_id: [knot.step_id]},
        registered_assumptions=_assumption_registry(knot.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        sandbox_pubkey=lambda _k: sandbox_key.public,
        registered_suites={suite_digest},
        registered_manifests={manifest_digest},
        strict=True,
    )
    assert not result_strict.is_ok()
    assert result_strict.unwrap_err().predicate == "AL-1"


# ---------------------------------------------------------------------------
# Test 13 — deterministic classifier smoke
# ---------------------------------------------------------------------------


def test_classify_position_deterministic() -> None:
    assert _classify_position("Yes, complete.") == "affirm"
    assert _classify_position("no, this fails.") == "deny"
    assert _classify_position("Actually reconsidering.") == "reconsider"
    assert _classify_position("The sky is blue.") == "unknown"
    # Mixed signals (affirm + deny) return unknown to avoid noise.
    assert _classify_position("yes and no") == "unknown"


# RACT 0.4.0
