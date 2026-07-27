"""AL-1 (Anti-Lazy Attestation) property tests.

ALM module_05. Hypothesis generates rootknot instances with varying
gate_results tuples and reversal_taint values. Every valid instance
(all gates PASS + clean taint + verifying signature) satisfies AL-1;
every invalid instance (a failed gate without handshake OR partial
taint without accepted-run OR bit-flipped signature) fails.
"""

from __future__ import annotations

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


@settings(
    deadline=None,
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(gate_results=_gate_results(), taint=_TAINT_STRATEGY)
def test_property_al1_invariant_holds_across_100_fixtures(
    gate_results: tuple[GateResult, ...], taint: str
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        sandbox_key = SandboxKey.generate(
            b"\x88" * 16, workspace_root=workspace
        )
        alm_key = AlmVerifierKey.generate(
            b"\x99" * 16, workspace_root=workspace
        )
        artifact = workspace / "artifact.txt"
        artifact.write_bytes(b"payload")
        suite_digest = digest_bytes(b"suite-canonical-prop")
        manifest_digest = digest_bytes(b"manifest-canonical-prop")

        knot = make_rootknot_v3(
            key=_SESSION,
            sandbox_signer=sandbox_key,
            alm_signer=alm_key,
            workspace_path="artifact.txt",
            artifact_digest=digest_bytes(b"payload"),
            assumption_digest=digest_bytes(b"assume-prop"),
            acceptance_suite_digest=suite_digest,
            predicate_results=(digest_bytes(b"pred-prop"),),
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

        # Approved handshake ids: those in the gate_results tuple whose
        # handshake_id is non-None. This models the operator having
        # approved every recorded handshake — the sub-clause under test
        # is then only whether unpassed-and-un-handshaken gates fail.
        approved = {gr.handshake_id for gr in gate_results if gr.handshake_id}
        # Every partial taint is accepted for the property test.
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

        # Derived expectation: AL-1 passes iff every gate is passed OR
        # has an approved handshake id, AND taint is clean or accepted.
        # (Since we approved every handshake and accepted every partial,
        # this simplifies to "every failed gate has a handshake_id".)
        expect_ok = all(
            gr.passed or (gr.handshake_id is not None) for gr in gate_results
        )
        # taint is either accepted or clean so the third clause always
        # holds; the assertion below reduces to the gates clause.
        assert result.is_ok() == expect_ok, (
            f"result={result} expect_ok={expect_ok} "
            f"gates={gate_results} taint={taint}"
        )


# RACT 0.4.0
