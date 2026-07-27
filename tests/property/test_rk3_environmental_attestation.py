"""RK-3 (Environmental Attestation) property tests.

module_06 (SUBSTRATE §7.2). RK-3 requires every v2 sidecar to carry a
valid environment signature, non-empty predicate results, and (when
context is supplied) a registered acceptance-suite digest and manifest
digest. v1 sidecars are skipped with a ``DeprecationWarning`` and
refused under ``strict=True``.
"""

from __future__ import annotations

import tempfile
import warnings
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ract.core.keys import SessionKey
from ract.core.provenance import ProvenanceIndex, verify_workspace
from ract.core.rootknot import Rootknot, make_rootknot, make_rootknot_v2
from ract.core.types import Digest, digest_bytes, make_plan_id, make_step_id
from ract.security.keys import SandboxKey


@pytest.fixture
def session_key() -> SessionKey:
    return SessionKey.load_or_create(b"\x00" * 16)


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


def _sample_v2(
    session_key: SessionKey,
    sandbox_key: SandboxKey,
    workspace: Path,
    content: bytes,
) -> tuple[Rootknot, Digest, Digest]:
    """Create a fresh v2 rootknot for a workspace artifact."""
    artifact = workspace / "artifact.txt"
    artifact.write_bytes(content)
    suite_digest = digest_bytes(b"suite-canonical")
    manifest_digest = digest_bytes(b"manifest-canonical")
    predicate_results = (digest_bytes(b"pred-1-result"),)
    knot = make_rootknot_v2(
        key=session_key,
        sandbox_signer=sandbox_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(content),
        assumption_digest=digest_bytes(b"assume"),
        acceptance_suite_digest=suite_digest,
        predicate_results=predicate_results,
        manifest_digest=manifest_digest,
    )
    return knot, suite_digest, manifest_digest


def test_rk3_ok_for_v2_sidecar_with_valid_env_signature(
    fresh_workspace: Path, session_key: SessionKey
) -> None:
    sandbox_key = SandboxKey.generate(b"\x01" * 16, workspace_root=fresh_workspace)
    knot, suite_digest, manifest_digest = _sample_v2(
        session_key, sandbox_key, fresh_workspace, b"hello"
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(
        knot, fresh_workspace / "artifact.txt", sandbox_pubkey=sandbox_key.public
    )

    # Non-strict: v2 verifies (RK-3 required, AL-1 skipped with warning).
    # ALM module_05 raised strict-mode's bar to "AL-1 required" — the
    # v2 sidecars are still fine at the non-strict floor, which is the
    # backwards-compatibility contract module_05's DoD commits to.
    result = verify_workspace(
        index,
        active_plans={knot.plan_id: [knot.step_id]},
        registered_assumptions=_registry(knot.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        sandbox_pubkey=lambda _k: sandbox_key.public,
        registered_suites={suite_digest},
        registered_manifests={manifest_digest},
    )
    assert result.is_ok(), result.unwrap_err()


def test_rk3_fails_for_v2_sidecar_with_forged_env_signature(
    fresh_workspace: Path, session_key: SessionKey
) -> None:
    sandbox_key = SandboxKey.generate(b"\x02" * 16, workspace_root=fresh_workspace)
    knot, suite_digest, manifest_digest = _sample_v2(
        session_key, sandbox_key, fresh_workspace, b"data"
    )
    # Forge: replace the environment signature with random bytes of the
    # right length so the verify path exercises the signature check
    # (not a length check).
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
        environment_signature=b"\x00" * 64,
        acceptance_suite_digest=knot.acceptance_suite_digest,
        predicate_results=knot.predicate_results,
        manifest_digest=knot.manifest_digest,
        schema_version=2,
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(
        forged, fresh_workspace / "artifact.txt", sandbox_pubkey=sandbox_key.public
    )

    result = verify_workspace(
        index,
        active_plans={forged.plan_id: [forged.step_id]},
        registered_assumptions=_registry(forged.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        sandbox_pubkey=lambda _k: sandbox_key.public,
        registered_suites={suite_digest},
        registered_manifests={manifest_digest},
        strict=True,
    )
    assert not result.is_ok()
    assert result.unwrap_err().predicate == "RK-3.1"


def test_rk3_fails_when_predicate_result_missing(
    fresh_workspace: Path, session_key: SessionKey
) -> None:
    sandbox_key = SandboxKey.generate(b"\x03" * 16, workspace_root=fresh_workspace)
    artifact = fresh_workspace / "artifact.txt"
    artifact.write_bytes(b"payload")
    suite_digest = digest_bytes(b"suite-canonical")
    manifest_digest = digest_bytes(b"manifest-canonical")
    # Empty predicate_results — must fail RK-3.3.
    knot = make_rootknot_v2(
        key=session_key,
        sandbox_signer=sandbox_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"payload"),
        assumption_digest=digest_bytes(b"assume"),
        acceptance_suite_digest=suite_digest,
        predicate_results=(),
        manifest_digest=manifest_digest,
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(knot, artifact, sandbox_pubkey=sandbox_key.public)

    result = verify_workspace(
        index,
        active_plans={knot.plan_id: [knot.step_id]},
        registered_assumptions=_registry(knot.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        sandbox_pubkey=lambda _k: sandbox_key.public,
        registered_suites={suite_digest},
        registered_manifests={manifest_digest},
        strict=True,
    )
    assert not result.is_ok()
    assert result.unwrap_err().predicate == "RK-3.3"


def test_rk3_skipped_with_warning_for_v1_sidecar(
    fresh_workspace: Path, session_key: SessionKey
) -> None:
    """v1 sidecars verify under RK-1 + RK-2 only; RK-3 skips with a warning."""
    artifact = fresh_workspace / "artifact.txt"
    artifact.write_bytes(b"legacy")
    plan_id = make_plan_id()
    step_id = make_step_id()
    knot = make_rootknot(
        session_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"legacy"),
        assumption_digest=digest_bytes(b"assume"),
        plan_id=plan_id,
        step_id=step_id,
    )
    assert knot.schema_version == 1
    index = ProvenanceIndex(fresh_workspace)
    index.save(knot, artifact)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = verify_workspace(
            index,
            active_plans={plan_id: [step_id]},
            registered_assumptions=_registry(knot.assumption_digest),
            generator_pubkey=lambda _g: session_key.public_key_bytes(),
        )
    assert result.is_ok(), result.unwrap_err()
    assert any(
        issubclass(w.category, DeprecationWarning)
        and "RK-3 skipped for v1 sidecar" in str(w.message)
        for w in caught
    ), [str(w.message) for w in caught]


def test_rk3_strict_refuses_v1_sidecar(
    fresh_workspace: Path, session_key: SessionKey
) -> None:
    artifact = fresh_workspace / "artifact.txt"
    artifact.write_bytes(b"legacy-strict")
    plan_id = make_plan_id()
    step_id = make_step_id()
    knot = make_rootknot(
        session_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"legacy-strict"),
        assumption_digest=digest_bytes(b"assume"),
        plan_id=plan_id,
        step_id=step_id,
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(knot, artifact)

    result = verify_workspace(
        index,
        active_plans={plan_id: [step_id]},
        registered_assumptions=_registry(knot.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        strict=True,
    )
    assert not result.is_ok()
    assert result.unwrap_err().predicate == "RK-3"


@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(content=st.binary(min_size=1, max_size=256))
def test_rk3_hypothesis_holds_after_every_step(
    content: bytes, fresh_workspace: Path, session_key: SessionKey
) -> None:
    """Hypothesis-generated plans: RK-3 holds after every step of every plan."""
    sandbox_key = SandboxKey.generate(b"\x04" * 16, workspace_root=fresh_workspace)
    knot, suite_digest, manifest_digest = _sample_v2(
        session_key, sandbox_key, fresh_workspace, content
    )
    index = ProvenanceIndex(fresh_workspace)
    index.save(
        knot, fresh_workspace / "artifact.txt", sandbox_pubkey=sandbox_key.public
    )

    # Non-strict: v2 verifies (RK-3 required, AL-1 skipped with warning).
    # ALM module_05 raised strict-mode's bar to "AL-1 required".
    result = verify_workspace(
        index,
        active_plans={knot.plan_id: [knot.step_id]},
        registered_assumptions=_registry(knot.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        sandbox_pubkey=lambda _k: sandbox_key.public,
        registered_suites={suite_digest},
        registered_manifests={manifest_digest},
    )
    assert result.is_ok(), result.unwrap_err()


# RACT 0.4.0
