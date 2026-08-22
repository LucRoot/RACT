"""v0.5.2 hardening module_01 -- v4-label-implies-v4-fields (verifier-side).

Closes deep-audit A F-2 (HIGH): the v0.5.1 verifier's ``_check_rk3``
never asserted that a v4-labelled payload actually carried the v4
fields. The construction-time check in ``__post_init__`` (F-1
closure) is bypassed by ``copy`` / ``pickle`` deserialisation
paths, so the VERIFIER-SIDE check is what closes the attack for
sidecars that arrive from disk / network / adversarial
serialisers.

Ox Alpha co-build (2026-08-22) Fork 3 gotcha #2 -- explicit: "Keep
the verifier-side F-2 assertion authoritative; post_init is
defense-in-depth, not the boundary."
"""

from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import pytest

from ract.core.keys import SessionKey
from ract.core.loop import WorkspaceSnapshot
from ract.core.provenance import ProvenanceIndex, verify_workspace
from ract.core.rootknot import (
    Rootknot,
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


@pytest.mark.parametrize(
    "strip_field",
    ["workspace_digest", "prompt_digest", "run_id"],
)
def test_v4_label_with_stripped_field_refused_by_verifier(
    fresh_workspace: Path, strip_field: str
) -> None:
    """A v4 knot with one v4 field smuggled to empty via post_init bypass fails verify."""
    session_key = SessionKey.load_or_create(b"\x50" * 16)
    sandbox_key = SandboxKey.generate(b"\x51" * 16, workspace_root=fresh_workspace)
    alm = _AlmSigner(b"\x52" * 16)

    artifact = fresh_workspace / "artifact.txt"
    artifact.write_bytes(b"data")
    suite_digest = digest_bytes(b"suite")
    manifest_digest = digest_bytes(b"manifest")
    predicate_results = (digest_bytes(b"pred-1"),)
    ws_digest = workspace_digest(WorkspaceSnapshot(files={}, timestamp=0.0))
    p_digest = compute_prompt_digest("intent")

    knot = make_rootknot_v4(
        key=session_key,
        sandbox_signer=sandbox_key,
        alm_signer=alm,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"data"),
        assumption_digest=digest_bytes(b"assume"),
        acceptance_suite_digest=suite_digest,
        predicate_results=predicate_results,
        manifest_digest=manifest_digest,
        gate_results=(),
        workspace_digest=ws_digest,
        prompt_digest=p_digest,
        run_id="run-v4-verify",
    )

    # Simulate a deserialisation-path bypass: strip one v4 field from
    # a frozen-dataclass copy via object.__setattr__. This mirrors the
    # Ox Alpha Fork 3 corner case #2 attack surface (copy / pickle
    # restore skip __post_init__). The verifier-side check must still
    # refuse.
    smuggled = copy.copy(knot)
    empty_value: object
    if strip_field == "run_id":
        empty_value = ""
    else:
        empty_value = None
    object.__setattr__(smuggled, strip_field, empty_value)

    index = ProvenanceIndex(fresh_workspace)
    index.all_knots = lambda: {"artifact.txt": smuggled}  # type: ignore[method-assign]

    result = verify_workspace(
        index,
        active_plans={smuggled.plan_id: [smuggled.step_id]},
        registered_assumptions=_registry(smuggled.assumption_digest),
        generator_pubkey=lambda _g: session_key.public_key_bytes(),
        sandbox_pubkey=lambda _k: sandbox_key.public,
        registered_suites={suite_digest},
        registered_manifests={manifest_digest},
        alm_pubkey=lambda _k: alm.public_key_bytes(),
    )
    assert not result.is_ok()
    violation = result.unwrap_err()
    assert violation.predicate == "RK-V4-LABEL-MISMATCH"
    assert strip_field in violation.detail


def test_v4_label_with_all_fields_present_still_verifies(
    fresh_workspace: Path,
) -> None:
    """A properly-constructed v4 knot still verifies end-to-end (no regression)."""
    session_key = SessionKey.load_or_create(b"\x60" * 16)
    sandbox_key = SandboxKey.generate(b"\x61" * 16, workspace_root=fresh_workspace)
    alm = _AlmSigner(b"\x62" * 16)

    artifact = fresh_workspace / "artifact.txt"
    artifact.write_bytes(b"ok")
    suite_digest = digest_bytes(b"suite-ok")
    manifest_digest = digest_bytes(b"manifest-ok")
    predicate_results = (digest_bytes(b"pred-ok"),)
    ws_digest = workspace_digest(WorkspaceSnapshot(files={}, timestamp=0.0))
    p_digest = compute_prompt_digest("intent-ok")

    knot = make_rootknot_v4(
        key=session_key,
        sandbox_signer=sandbox_key,
        alm_signer=alm,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"ok"),
        assumption_digest=digest_bytes(b"assume-ok"),
        acceptance_suite_digest=suite_digest,
        predicate_results=predicate_results,
        manifest_digest=manifest_digest,
        gate_results=(),
        workspace_digest=ws_digest,
        prompt_digest=p_digest,
        run_id="run-v4-ok",
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
        alm_pubkey=lambda _k: alm.public_key_bytes(),
    )
    assert result.is_ok(), result.unwrap_err()


# RACT 0.5.2
