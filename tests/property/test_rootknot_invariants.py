"""Property tests for Rootknot RK-1 and RK-2 invariants."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from rootact.core.keys import SessionKey
from rootact.core.provenance import ProvenanceIndex, verify_workspace
from rootact.core.rootknot import Rootknot, make_rootknot
from rootact.core.types import Digest, digest_bytes, make_plan_id, make_step_id


@pytest.fixture
def session_key() -> SessionKey:
    return SessionKey.load_or_create(b"\x00" * 16)


@pytest.fixture
def fresh_workspace() -> Path:  # type: ignore[misc]
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _registry(assumption_digest: Digest) -> dict:
    """Return a tiny assumption object whose state is active."""
    return {assumption_digest: type("A", (), {"state": type("S", (), {"name": "ACTIVE"})()})()}


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    path=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))),
    content=st.binary(min_size=0, max_size=256),
)
def test_signed_rootknot_verifies(path: str, content: bytes, session_key: SessionKey) -> None:
    """A freshly signed Rootknot verifies against its public key."""
    plan_id = make_plan_id()
    step_id = make_step_id()
    assumption = digest_bytes(b"assume")
    artifact_digest = digest_bytes(content)
    knot = make_rootknot(
        session_key,
        workspace_path=path,
        artifact_digest=artifact_digest,
        assumption_digest=assumption,
        plan_id=plan_id,
        step_id=step_id,
    )
    assert knot.verify(session_key.public_key_bytes())


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    path=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))),
    content=st.binary(min_size=0, max_size=256),
    field=st.sampled_from(["plan_id", "step_id", "artifact_digest", "workspace_path"]),
)
def test_tampered_field_breaks_verification(
    path: str, content: bytes, field: str, session_key: SessionKey
) -> None:
    """Tampering with any canonical field breaks signature verification."""
    assumption = digest_bytes(b"assume")
    knot = make_rootknot(
        session_key,
        workspace_path=path,
        artifact_digest=digest_bytes(content),
        assumption_digest=assumption,
    )
    if field == "plan_id":
        tampered = Rootknot(**{**knot.__dict__, "plan_id": make_plan_id()})
    elif field == "step_id":
        tampered = Rootknot(**{**knot.__dict__, "step_id": make_step_id()})
    elif field == "artifact_digest":
        tampered = Rootknot(**{**knot.__dict__, "artifact_digest": digest_bytes(b"other")})
    else:
        tampered = Rootknot(**{**knot.__dict__, "workspace_path": path + "x"})
    assert not tampered.verify(session_key.public_key_bytes())


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(content=st.binary(min_size=0, max_size=256))
def test_verify_workspace_accepts_valid_artifact(
    content: bytes, fresh_workspace: Path, session_key: SessionKey
) -> None:
    """RK-1 holds for a workspace with one valid, signed artifact."""
    plan_id = make_plan_id()
    step_id = make_step_id()
    assumption = digest_bytes(b"assume")
    artifact = fresh_workspace / "artifact.txt"
    artifact.write_bytes(content)
    index = ProvenanceIndex(fresh_workspace)
    knot = make_rootknot(
        session_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(content),
        assumption_digest=assumption,
        plan_id=plan_id,
        step_id=step_id,
    )
    index.save(knot, artifact)
    result = verify_workspace(
        index,
        active_plans={plan_id: [step_id]},
        registered_assumptions=_registry(assumption),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
    )
    assert result.is_ok()


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(content=st.binary(min_size=0, max_size=256))
def test_verify_workspace_rejects_mutated_artifact(
    content: bytes, fresh_workspace: Path, session_key: SessionKey
) -> None:
    """Mutating an artifact after indexing violates RK-1.1."""
    plan_id = make_plan_id()
    step_id = make_step_id()
    assumption = digest_bytes(b"assume")
    artifact = fresh_workspace / "artifact.txt"
    artifact.write_bytes(content)
    index = ProvenanceIndex(fresh_workspace)
    knot = make_rootknot(
        session_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(content),
        assumption_digest=assumption,
        plan_id=plan_id,
        step_id=step_id,
    )
    index.save(knot, artifact)
    artifact.write_bytes(b"tampered")
    result = verify_workspace(
        index,
        active_plans={plan_id: [step_id]},
        registered_assumptions=_registry(assumption),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
    )
    assert not result.is_ok()
    assert result.unwrap_err().predicate == "RK-1.1"


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(content=st.binary(min_size=0, max_size=256))
def test_verify_workspace_rejects_missing_parent(
    content: bytes, fresh_workspace: Path, session_key: SessionKey
) -> None:
    """A rootknot whose parent digest does not resolve violates RK-1.6."""
    plan_id = make_plan_id()
    step_id = make_step_id()
    assumption = digest_bytes(b"assume")
    artifact = fresh_workspace / "artifact.txt"
    artifact.write_bytes(content)
    index = ProvenanceIndex(fresh_workspace)
    knot = make_rootknot(
        session_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(content),
        assumption_digest=assumption,
        plan_id=plan_id,
        step_id=step_id,
        parent_digests=(digest_bytes(b"missing-parent"),),
    )
    index.save(knot, artifact)
    result = verify_workspace(
        index,
        active_plans={plan_id: [step_id]},
        registered_assumptions=_registry(assumption),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
    )
    assert not result.is_ok()
    assert result.unwrap_err().predicate == "RK-1.6"


# RACT 0.2.0
