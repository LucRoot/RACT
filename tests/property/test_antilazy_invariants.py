"""AL-1 (Anti-Lazy Attestation) property tests.

ALM module_05. AL-1 has three sub-clauses (module_05 spec named four,
but the shipped ``_check_al1`` in ``src/ract/core/provenance.py`` has
AL-1.1 / AL-1.2 / AL-1.3 only). Each sub-clause is exercised
independently by its own property test so a mismatch on one sub-clause
fails that sub-clause's assertion regardless of the other two:

- AL-1.1 (signature verifies): bit-flipped ``antilazy_signature`` fails.
- AL-1.2 (gates): a failed gate without an approved handshake fails.
- AL-1.3 (taint): ``reversal_taint="partial"`` without the plan_id in
  ``accepted_partial_taint_runs`` fails.
"""

from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ract.core.keys import SessionKey
from ract.core.provenance import ProvenanceIndex, verify_workspace
from ract.core.rootknot import GateResult, make_rootknot_v3
from ract.core.types import Digest, digest_bytes
from ract.security.alm_verifier_key import AlmVerifierKey
from ract.security.keys import SandboxKey


# Persistent per-session keys so the state directory isn't hammered by
# hundreds of key writes.
_SESSION = SessionKey.load_or_create(b"\x77" * 16)


@st.composite
def _gate_results(draw) -> tuple[GateResult, ...]:
    n = draw(st.integers(min_value=1, max_value=8))
    out: list[GateResult] = []
    for i in range(1, n + 1):
        passed = draw(st.booleans())
        has_handshake = draw(st.booleans())
        out.append(
            GateResult(
                gate_id=f"G{i}",
                passed=passed,
                evidence_digest=digest_bytes(f"g{i}-evidence".encode()),
                handshake_id=("H-" + str(i)) if has_handshake else None,
            )
        )
    return tuple(out)


_TAINT_STRATEGY = st.sampled_from(("clean", "partial"))


def _assumption_registry(assumption_digest: Digest) -> dict:
    return {
        assumption_digest: type(
            "A", (), {"state": type("S", (), {"name": "ACTIVE"})()}
        )()
    }


def _fresh_env(nonce: bytes) -> tuple[Path, SandboxKey, AlmVerifierKey, Digest, Digest]:
    """Build a fresh workspace with sandbox+ALM keys plus two digests.

    Kept separate so each property test owns its temp directory and can
    call ``dataclasses.replace`` freely without stepping on siblings.
    """
    workspace = Path(tempfile.mkdtemp())
    sandbox_key = SandboxKey.generate(b"\x88" * 16, workspace_root=workspace)
    alm_key = AlmVerifierKey.generate(b"\x99" * 16, workspace_root=workspace)
    suite_digest = digest_bytes(b"suite-canonical-prop-" + nonce)
    manifest_digest = digest_bytes(b"manifest-canonical-prop-" + nonce)
    return workspace, sandbox_key, alm_key, suite_digest, manifest_digest


@settings(
    deadline=None,
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(gate_results=_gate_results(), taint=_TAINT_STRATEGY)
def test_property_al1_2_gate_results_independent(
    gate_results: tuple[GateResult, ...], taint: str
) -> None:
    """AL-1.2 fires exactly when a failed gate lacks an approved handshake.

    AL-1.1 is neutralised (signature is the freshly signed one) and
    AL-1.3 is neutralised (every partial taint is accepted) so the
    outcome depends solely on AL-1.2.
    """
    workspace, sandbox_key, alm_key, suite_digest, manifest_digest = _fresh_env(b"g")
    artifact = workspace / "artifact.txt"
    artifact.write_bytes(b"payload-g")

    knot = make_rootknot_v3(
        key=_SESSION,
        sandbox_signer=sandbox_key,
        alm_signer=alm_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"payload-g"),
        assumption_digest=digest_bytes(b"assume-g"),
        acceptance_suite_digest=suite_digest,
        predicate_results=(digest_bytes(b"pred-g"),),
        manifest_digest=manifest_digest,
        gate_results=gate_results,
        reversal_taint=taint,  # type: ignore[arg-type]
    )
    index = ProvenanceIndex(workspace)
    index.save(
        knot,
        artifact,
        sandbox_pubkey=sandbox_key.public,
        alm_pubkey=alm_key.public,
    )

    approved = {gr.handshake_id for gr in gate_results if gr.handshake_id}
    accepted_partial = {knot.plan_id} if taint == "partial" else set()

    result = verify_workspace(
        index,
        active_plans={knot.plan_id: [knot.step_id]},
        registered_assumptions=_assumption_registry(knot.assumption_digest),
        generator_pubkey=lambda _g: _SESSION.public_key_bytes(),
        sandbox_pubkey=lambda _k: sandbox_key.public,
        alm_pubkey=lambda _k: alm_key.public,
        registered_suites={suite_digest},
        registered_manifests={manifest_digest},
        approved_gate_exceptions=approved,
        accepted_partial_taint_runs=accepted_partial,
        strict=True,
    )

    expect_ok = all(gr.passed or (gr.handshake_id is not None) for gr in gate_results)
    assert result.is_ok() == expect_ok, (
        f"result={result} expect_ok={expect_ok} gates={gate_results} taint={taint}"
    )
    if not expect_ok:
        assert result.unwrap_err().predicate == "AL-1.2"


@settings(
    deadline=None,
    max_examples=25,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    bit_position=st.integers(min_value=0, max_value=63 * 8 + 7),
    also_flip_byte=st.booleans(),
)
def test_property_al1_1_signature_bitflip_fails(
    bit_position: int, also_flip_byte: bool
) -> None:
    """AL-1.1 fires when the ``antilazy_signature`` is mutated by any bit.

    An ed25519 signature is 64 bytes. Flipping any bit — plus optionally
    a second bit in a distant byte — must always fail verification, so
    the property is that AL-1.1 rejects every mutant unconditionally.
    Gates are all-PASS + taint is clean so AL-1.2 and AL-1.3 are
    neutralised; a failure surfaces at AL-1.1 exclusively.
    """
    workspace, sandbox_key, alm_key, suite_digest, manifest_digest = _fresh_env(b"s")
    artifact = workspace / "artifact.txt"
    artifact.write_bytes(b"payload-s")

    knot = make_rootknot_v3(
        key=_SESSION,
        sandbox_signer=sandbox_key,
        alm_signer=alm_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"payload-s"),
        assumption_digest=digest_bytes(b"assume-s"),
        acceptance_suite_digest=suite_digest,
        predicate_results=(digest_bytes(b"pred-s"),),
        manifest_digest=manifest_digest,
        gate_results=(
            GateResult(
                gate_id="G1",
                passed=True,
                evidence_digest=digest_bytes(b"g1-s"),
            ),
        ),
        reversal_taint="clean",
    )

    # Flip one bit (and optionally a distant second bit) of the signature.
    sig = bytearray(knot.antilazy_signature)
    if not sig:
        # No signature to flip — nothing to test on this pathological input.
        return
    byte_idx = (bit_position // 8) % len(sig)
    bit_idx = bit_position % 8
    sig[byte_idx] ^= 1 << bit_idx
    if also_flip_byte:
        distant = (byte_idx + len(sig) // 2) % len(sig)
        sig[distant] ^= 0x01
    flipped = bytes(sig)

    flipped_knot = dataclasses.replace(knot, antilazy_signature=flipped)
    index = ProvenanceIndex(workspace)
    index.save(
        flipped_knot,
        artifact,
        sandbox_pubkey=sandbox_key.public,
        alm_pubkey=alm_key.public,
    )

    result = verify_workspace(
        index,
        active_plans={flipped_knot.plan_id: [flipped_knot.step_id]},
        registered_assumptions=_assumption_registry(flipped_knot.assumption_digest),
        generator_pubkey=lambda _g: _SESSION.public_key_bytes(),
        sandbox_pubkey=lambda _k: sandbox_key.public,
        alm_pubkey=lambda _k: alm_key.public,
        registered_suites={suite_digest},
        registered_manifests={manifest_digest},
        accepted_partial_taint_runs=set(),
        strict=True,
    )

    assert not result.is_ok(), (
        "AL-1.1 must reject a bit-flipped anti-lazy signature; "
        f"bit={bit_position} distant_flip={also_flip_byte}"
    )
    assert result.unwrap_err().predicate == "AL-1.1"


@settings(
    deadline=None,
    max_examples=25,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    accept=st.booleans(),
    n_extra_accepted=st.integers(min_value=0, max_value=3),
)
def test_property_al1_3_partial_taint_requires_accept(
    accept: bool, n_extra_accepted: int
) -> None:
    """AL-1.3 fires exactly when partial taint is not accepted.

    A knot with ``reversal_taint="partial"`` verifies iff its ``plan_id``
    appears in ``accepted_partial_taint_runs``. Extra accepted ids that
    are NOT this knot's plan_id must not save it. Gates are all-PASS and
    signature is the freshly signed one, so AL-1.1 and AL-1.2 are
    neutralised and any failure surfaces at AL-1.3 exclusively.
    """
    workspace, sandbox_key, alm_key, suite_digest, manifest_digest = _fresh_env(b"t")
    artifact = workspace / "artifact.txt"
    artifact.write_bytes(b"payload-t")

    knot = make_rootknot_v3(
        key=_SESSION,
        sandbox_signer=sandbox_key,
        alm_signer=alm_key,
        workspace_path="artifact.txt",
        artifact_digest=digest_bytes(b"payload-t"),
        assumption_digest=digest_bytes(b"assume-t"),
        acceptance_suite_digest=suite_digest,
        predicate_results=(digest_bytes(b"pred-t"),),
        manifest_digest=manifest_digest,
        gate_results=(
            GateResult(
                gate_id="G1",
                passed=True,
                evidence_digest=digest_bytes(b"g1-t"),
            ),
        ),
        reversal_taint="partial",
    )
    index = ProvenanceIndex(workspace)
    index.save(
        knot,
        artifact,
        sandbox_pubkey=sandbox_key.public,
        alm_pubkey=alm_key.public,
    )

    # Build an accepted-set that either contains this plan_id or does
    # not, plus arbitrary decoy plan_ids that must not save an unaccepted
    # run.
    decoys = {digest_bytes(f"decoy-{i}".encode()) for i in range(n_extra_accepted)}
    accepted: set[bytes] = set(decoys)
    if accept:
        accepted.add(knot.plan_id)

    result = verify_workspace(
        index,
        active_plans={knot.plan_id: [knot.step_id]},
        registered_assumptions=_assumption_registry(knot.assumption_digest),
        generator_pubkey=lambda _g: _SESSION.public_key_bytes(),
        sandbox_pubkey=lambda _k: sandbox_key.public,
        alm_pubkey=lambda _k: alm_key.public,
        registered_suites={suite_digest},
        registered_manifests={manifest_digest},
        accepted_partial_taint_runs=accepted,
        strict=True,
    )

    if accept:
        assert result.is_ok(), (
            "AL-1.3 must admit a partial-taint knot whose plan_id is in "
            f"accepted_partial_taint_runs; extra_decoys={n_extra_accepted}"
        )
    else:
        assert not result.is_ok(), (
            "AL-1.3 must reject a partial-taint knot whose plan_id is "
            f"NOT in accepted_partial_taint_runs; extra_decoys={n_extra_accepted}"
        )
        assert result.unwrap_err().predicate == "AL-1.3"


# RACT 0.4.0
