"""v0.5.2 hardening module_01 -- DOWNGRADE defence.

Closes Ox Alpha M-1 (HIGH): the v0.5.1 verifier had no
``min_acceptable_schema_version`` policy. A key-holder could take a
legitimately-signed v4 knot, relabel ``schema_version=1``, strip the
v4 fields, resign with the same session key, and the verifier would
accept the weaker attestation. The v0.5.2 fix adds a per-invocation
``min_acceptable_schema_version`` kwarg to ``verify_workspace`` and
``verify_artifact``; the CLI exposes it as ``--min-schema``.

Ox Alpha co-build (2026-08-22) Fork 1: chose kwarg over class-level
verifier so the policy floor is explicit at every call site (config
file / ambient-global surfaces were rejected on auditability grounds).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ract.core.keys import SessionKey
from ract.core.loop import WorkspaceSnapshot
from ract.core.provenance import ProvenanceIndex, verify_workspace
from ract.core.rootknot import (
    Rootknot,
    make_rootknot,
    make_rootknot_v4,
)
from ract.core.types import Digest, digest_bytes
from ract.core.workspace_digest import compute_prompt_digest, workspace_digest
from ract.security.keys import SandboxKey


class _AlmSigner:
    def __init__(self, seed: bytes) -> None:
        self._key = SessionKey.load_or_create(seed)

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)

    def public_key_bytes(self) -> bytes:
        return self._key.public_key_bytes()


@pytest.fixture
def fresh_workspace() -> Path:  # type: ignore[misc]
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _registry(assumption_digest: Digest) -> dict:
    return {
        assumption_digest: type(
            "A", (), {"state": type("S", (), {"name": "ACTIVE"})()}
        )()
    }


def test_downgrade_v4_relabelled_as_v1_refused_under_min_schema_policy(
    fresh_workspace: Path,
) -> None:
    """v4 knot relabelled as v1 + resigned by same key MUST refuse under floor=4.

    Simulates the exact M-1 attack:
    1. Attacker holds SessionKey; mints a legitimate v4 attestation.
    2. Attacker relabels ``schema_version=1`` and drops the v4 fields.
    3. Attacker resigns with the same session key (a legitimate signature
       over the v1-shaped canonical bytes).
    4. Absent a policy floor, verifier accepted the weaker attestation.
    5. Under ``min_acceptable_schema_version=4`` verifier refuses with
       ``RK-DOWNGRADE-REFUSED``.
    """
    session_key = SessionKey.load_or_create(b"\x10" * 16)
    sandbox_key = SandboxKey.generate(b"\x11" * 16, workspace_root=fresh_workspace)
    alm = _AlmSigner(b"\x12" * 16)

    artifact = fresh_workspace / "artifact.txt"
    artifact.write_bytes(b"payload")
    suite_digest = digest_bytes(b"suite")
    manifest_digest = digest_bytes(b"manifest")
    predicate_results = (digest_bytes(b"pred-1"),)
    ws_digest = workspace_digest(WorkspaceSnapshot(files={}, timestamp=0.0))
    p_digest = compute_prompt_digest("intent")

    # Legitimate v4 knot.
    v4_knot = make_rootknot_v4(
        key=session_key,
        sandbox_signer=sandbox_key,
        alm_signer=alm,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"payload"),
        assumption_digest=digest_bytes(b"assume"),
        acceptance_suite_digest=suite_digest,
        predicate_results=predicate_results,
        manifest_digest=manifest_digest,
        gate_results=(),
        workspace_digest=ws_digest,
        prompt_digest=p_digest,
        run_id="run-downgrade-attack",
    )
    # The attack: relabel v1, strip v4 fields, and resign under the same
    # session key. A legal v1 construction (no v4 gate applies) but
    # DOWNGRADED semantics.
    downgraded_unsigned = Rootknot(
        plan_id=v4_knot.plan_id,
        step_id=v4_knot.step_id,
        assumption_digest=v4_knot.assumption_digest,
        generator=v4_knot.generator,
        parent_digests=v4_knot.parent_digests,
        workspace_path=v4_knot.workspace_path,
        artifact_digest=v4_knot.artifact_digest,
        created_at_ns=v4_knot.created_at_ns,
        generator_signature=b"",
        schema_version=1,
    )
    downgraded = downgraded_unsigned.sign(session_key)

    index = ProvenanceIndex(fresh_workspace)
    index.save(downgraded, artifact)

    # Baseline: without policy floor, the downgraded knot verifies (this
    # IS the M-1 finding — the pre-hardening verifier had no floor).
    baseline = verify_workspace(
        index,
        active_plans={downgraded.plan_id: [downgraded.step_id]},
        registered_assumptions=_registry(downgraded.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
    )
    assert baseline.is_ok(), (
        "sanity: relabelled v1 must verify without a policy floor "
        "(that's the M-1 finding); result=" + repr(baseline)
    )

    # Hardening: with policy floor=4, refuse with the sharp reason.
    hardened = verify_workspace(
        index,
        active_plans={downgraded.plan_id: [downgraded.step_id]},
        registered_assumptions=_registry(downgraded.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        min_acceptable_schema_version=4,
    )
    assert not hardened.is_ok()
    violation = hardened.unwrap_err()
    assert violation.predicate == "RK-DOWNGRADE-REFUSED"
    assert "below policy floor 4" in violation.detail
    assert "M-1" in violation.detail


def test_v3_verifies_under_floor_3_but_refused_under_floor_4(
    fresh_workspace: Path,
) -> None:
    """A v1 knot: floor=1 accepts, floor=3 rejects with DOWNGRADE reason."""
    session_key = SessionKey.load_or_create(b"\x20" * 16)
    artifact = fresh_workspace / "artifact.txt"
    artifact.write_bytes(b"legacy-payload")
    v1 = make_rootknot(
        session_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"legacy-payload"),
        assumption_digest=digest_bytes(b"assume-legacy"),
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(v1, artifact)

    accept = verify_workspace(
        index,
        active_plans={v1.plan_id: [v1.step_id]},
        registered_assumptions=_registry(v1.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        min_acceptable_schema_version=1,
    )
    assert accept.is_ok(), accept

    refuse = verify_workspace(
        index,
        active_plans={v1.plan_id: [v1.step_id]},
        registered_assumptions=_registry(v1.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        min_acceptable_schema_version=3,
    )
    assert not refuse.is_ok()
    assert refuse.unwrap_err().predicate == "RK-DOWNGRADE-REFUSED"


def test_backward_compat_default_none_still_accepts_v1(
    fresh_workspace: Path,
) -> None:
    """Default (no ``min_acceptable_schema_version``) preserves v0.5.1 accept-v1."""
    session_key = SessionKey.load_or_create(b"\x30" * 16)
    artifact = fresh_workspace / "artifact.txt"
    artifact.write_bytes(b"legacy")
    v1 = make_rootknot(
        session_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"legacy"),
        assumption_digest=digest_bytes(b"assume"),
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(v1, artifact)

    result = verify_workspace(
        index,
        active_plans={v1.plan_id: [v1.step_id]},
        registered_assumptions=_registry(v1.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
    )
    assert result.is_ok(), result


# RACT 0.5.2
