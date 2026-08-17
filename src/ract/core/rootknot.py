"""Signed provenance capability for every artifact produced by the recursion loop.

v0.4 extension (SUBSTRATE §7.2). The Rootknot is preserved as the sacred
spine, but its schema is extended: alongside the generator's signature,
each v2 rootknot carries an *environment* signature bound to the run's
sandbox key, plus digests of the acceptance suite, the predicate results
that gated the write, and the capability manifest. RK-3 (Environmental
Attestation) in ``ract.core.provenance`` verifies these together.

The v0.3 baseline field name ``signature`` remains as a **deprecated**
compatibility alias for ``generator_signature`` (scheduled for removal in
v0.5). The alias emits a ``DeprecationWarning``; v0.3 callers keep
working during the migration.

Reference sources:

- SUBSTRATE spec §7 (The Trust-Direction Fix, Rootknot Preserved).
- REBUILD spec §3 (Rootknot Made Real) — v0.3 baseline this extends.
- RFC 8032 (Edwards-curve Digital Signature Algorithm, ed25519).
- ``cryptography`` public docs: ``https://cryptography.io/``.
"""

from __future__ import annotations

import json
import time
import warnings
from dataclasses import dataclass, field
from typing import Literal

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)

from ract.core.keys import SessionKey, verify
from ract.core.types import Digest, PlanId, StepId, make_plan_id, make_step_id


# Zero digest sentinel — used for v1 rootknots that do not carry the v0.4
# environment-attestation fields. RK-3 skips-with-warning for any knot
# whose ``schema_version`` is 1 (per module_06 lateral chain branch A).
_ZERO_DIGEST: Digest = Digest(b"\x00" * 32)


# ---------------------------------------------------------------------------
# v0.4 ALM module_05 — Gate result value carried inside the v3 Rootknot.
# ---------------------------------------------------------------------------


ReversalTaint = Literal["clean", "partial"]


@dataclass(frozen=True)
class GateResult:
    """One anti-lazy gate report snapshotted into the Rootknot.

    ``gate_id`` is one of ``"G1"`` through ``"G8"`` (ALM §3). ``passed``
    is the boolean outcome of the gate this iteration. ``evidence_digest``
    is a 32-byte SHA-256 over the on-disk report (patchdiff report,
    coverage delta report, mutation report, ...); a verifier reconstructs
    the report from disk and re-hashes to confirm the digest matches.
    ``handshake_id`` is set when the gate failed but an operator
    handshake overrode the failure; the verifier looks the id up in the
    HandshakeRegistry and confirms status is ``approved``.

    v3 rootknots serialize the full tuple of ``GateResult`` records into
    the signed canonical bytes so the ALM verifier key is signing over
    the exact gate-outcome set the completion claims.
    """

    gate_id: str
    passed: bool
    evidence_digest: Digest = _ZERO_DIGEST
    handshake_id: str | None = None

    def canonical_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable stable-key form of this result."""
        payload: dict[str, object] = {
            "gate_id": self.gate_id,
            "passed": bool(self.passed),
            "evidence_digest": self.evidence_digest.hex(),
        }
        if self.handshake_id is not None:
            payload["handshake_id"] = self.handshake_id
        return payload


@dataclass(frozen=True)
class GeneratorRef:
    """Identity of the generator that authored an artifact."""

    model_name: str
    model_version: str
    session_id: bytes
    public_key_id: Digest


@dataclass(frozen=True)
class Rootknot:
    """Provenance capability for every artifact produced by the recursion loop.

    A Rootknot is a signed statement that binds an artifact to
    (a) the plan step that produced it,
    (b) the assumption that justified the step,
    (c) the generator that authored it,
    (d) the upstream artifacts it derives from, and
    (v0.4 additions, SUBSTRATE §7.2)
    (e) the sandbox key that attested the environment,
    (f) the acceptance suite that gated the write,
    (g) the predicate results that gated the write, and
    (h) the capability manifest in force at the time of the write.

    ``generator_signature`` is ed25519 over ``canonical_bytes()``.
    ``environment_signature`` is ed25519 over the same bytes but by the
    sandbox key (the environment attester, SUBSTRATE §7.1). ``schema_version``
    is 1 for v0.3-compatible rootknots (v1 sidecars) and 2 for v0.4
    rootknots (v2 sidecars); the canonical form dispatches on the version so
    v1 signatures continue to verify after this module lands.
    """

    plan_id: PlanId
    step_id: StepId
    assumption_digest: Digest
    generator: GeneratorRef
    parent_digests: tuple[Digest, ...]
    workspace_path: str
    artifact_digest: Digest
    created_at_ns: int
    generator_signature: bytes
    # v0.4 additions — default zeros / empties so v0.3 constructors still work.
    environment_signature: bytes = b""
    acceptance_suite_digest: Digest = _ZERO_DIGEST
    predicate_results: tuple[Digest, ...] = field(default_factory=tuple)
    manifest_digest: Digest = _ZERO_DIGEST
    # v0.4 ALM module_05 additions — default zeros / clean so v0.3 and v0.4
    # substrate constructors still work.
    antilazy_signature: bytes = b""
    gate_results: tuple[GateResult, ...] = field(default_factory=tuple)
    reversal_taint: ReversalTaint = "clean"
    # 1 = v0.3-compat (v1 sidecar); 2 = v0.4 substrate (v2 sidecar);
    # 3 = v0.4 ALM (v3 sidecar). Canonical bytes dispatch on this so a
    # v1 or v2 signature never breaks under v0.4-ALM code load.
    schema_version: int = 1

    # ------------------------------------------------------------------
    # Deprecated v0.3 alias for the field renamed by module_06.
    # Scheduled for removal in v0.5.
    # ------------------------------------------------------------------

    @property
    def signature(self) -> bytes:
        """Deprecated v0.3 alias for ``generator_signature``.

        Emits a ``DeprecationWarning`` on read; scheduled for removal in
        v0.5 (see module_06 step 2). Kept so existing callers do not
        break under the schema extension.
        """
        warnings.warn(
            "Rootknot.signature is deprecated in v0.4; use "
            "Rootknot.generator_signature instead. The alias will be "
            "removed in v0.5.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.generator_signature

    # ------------------------------------------------------------------
    # Canonical serialisation
    # ------------------------------------------------------------------

    def canonical_bytes(self) -> bytes:
        """Return the deterministic serialisation used for signing.

        v1 form (``schema_version == 1``) preserves the exact v0.3 bytes
        so rootknots signed before v0.4 continue to verify. v2 form
        appends the four new attestation fields in a stable order.
        """
        payload: dict[str, object] = {
            "plan_id": self.plan_id.hex(),
            "step_id": self.step_id.hex(),
            "assumption_digest": self.assumption_digest.hex(),
            "generator": {
                "model_name": self.generator.model_name,
                "model_version": self.generator.model_version,
                "session_id": self.generator.session_id.hex(),
                "public_key_id": self.generator.public_key_id.hex(),
            },
            "parent_digests": [d.hex() for d in self.parent_digests],
            "workspace_path": self.workspace_path,
            "artifact_digest": self.artifact_digest.hex(),
            "created_at_ns": self.created_at_ns,
        }
        if self.schema_version >= 2:
            payload["acceptance_suite_digest"] = self.acceptance_suite_digest.hex()
            payload["predicate_results"] = [d.hex() for d in self.predicate_results]
            payload["manifest_digest"] = self.manifest_digest.hex()
            payload["schema_version"] = self.schema_version
        if self.schema_version >= 3:
            # ALM module_05: gate_results + reversal_taint feed the signed
            # canonical bytes so the anti-lazy signature attests the exact
            # gate-outcome set the completion claims. The antilazy_signature
            # itself is NOT part of the canonical bytes — it signs over
            # them, so including it would be a chicken-and-egg loop.
            payload["gate_results"] = [gr.canonical_dict() for gr in self.gate_results]
            payload["reversal_taint"] = self.reversal_taint
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )

    # ------------------------------------------------------------------
    # Signing / verifying
    # ------------------------------------------------------------------

    def sign(self, key: SessionKey) -> Rootknot:
        """Return a new Rootknot whose ``generator_signature`` is set."""
        return Rootknot(
            plan_id=self.plan_id,
            step_id=self.step_id,
            assumption_digest=self.assumption_digest,
            generator=self.generator,
            parent_digests=self.parent_digests,
            workspace_path=self.workspace_path,
            artifact_digest=self.artifact_digest,
            created_at_ns=self.created_at_ns,
            generator_signature=key.sign(self.canonical_bytes()),
            environment_signature=self.environment_signature,
            acceptance_suite_digest=self.acceptance_suite_digest,
            predicate_results=self.predicate_results,
            manifest_digest=self.manifest_digest,
            antilazy_signature=self.antilazy_signature,
            gate_results=self.gate_results,
            reversal_taint=self.reversal_taint,
            schema_version=self.schema_version,
        )

    def attest_environment(self, sandbox_signer) -> Rootknot:  # type: ignore[no-untyped-def]
        """Return a new Rootknot whose ``environment_signature`` is set.

        ``sandbox_signer`` is any object with a ``sign(bytes) -> bytes``
        method — typically a ``ract.security.keys.SandboxKey`` (see
        module_06 step 3). The environment signature is over the same
        canonical bytes as the generator signature; RK-3 verifies both
        under distinct pubkeys.
        """
        return Rootknot(
            plan_id=self.plan_id,
            step_id=self.step_id,
            assumption_digest=self.assumption_digest,
            generator=self.generator,
            parent_digests=self.parent_digests,
            workspace_path=self.workspace_path,
            artifact_digest=self.artifact_digest,
            created_at_ns=self.created_at_ns,
            generator_signature=self.generator_signature,
            environment_signature=sandbox_signer.sign(self.canonical_bytes()),
            acceptance_suite_digest=self.acceptance_suite_digest,
            predicate_results=self.predicate_results,
            manifest_digest=self.manifest_digest,
            antilazy_signature=self.antilazy_signature,
            gate_results=self.gate_results,
            reversal_taint=self.reversal_taint,
            schema_version=self.schema_version,
        )

    def attest_antilazy(self, alm_signer) -> Rootknot:  # type: ignore[no-untyped-def]
        """Return a new Rootknot whose ``antilazy_signature`` is set.

        ``alm_signer`` is any object with a ``sign(bytes) -> bytes``
        method — typically a ``ract.security.alm_verifier_key.AlmVerifierKey``.
        The anti-lazy signature is over the same canonical bytes as the
        generator and environment signatures; AL-1 verifies it under the
        ALM verifier's distinct pubkey (ALM §5).

        Precondition: ``schema_version`` must be at least 3 — earlier
        schemas do not include ``gate_results`` or ``reversal_taint`` in
        the canonical bytes, so an anti-lazy signature over v1 or v2
        canonical bytes would not attest what the invariant claims. The
        caller is expected to build a v3 knot via ``make_rootknot_v3``.
        """
        if self.schema_version < 3:
            raise ValueError(
                "attest_antilazy requires schema_version >= 3; "
                f"got {self.schema_version}. Use make_rootknot_v3 to "
                "construct the ALM-shaped Rootknot."
            )
        return Rootknot(
            plan_id=self.plan_id,
            step_id=self.step_id,
            assumption_digest=self.assumption_digest,
            generator=self.generator,
            parent_digests=self.parent_digests,
            workspace_path=self.workspace_path,
            artifact_digest=self.artifact_digest,
            created_at_ns=self.created_at_ns,
            generator_signature=self.generator_signature,
            environment_signature=self.environment_signature,
            acceptance_suite_digest=self.acceptance_suite_digest,
            predicate_results=self.predicate_results,
            manifest_digest=self.manifest_digest,
            antilazy_signature=alm_signer.sign(self.canonical_bytes()),
            gate_results=self.gate_results,
            reversal_taint=self.reversal_taint,
            schema_version=self.schema_version,
        )

    def verify(self, pubkey: bytes) -> bool:
        """Verify the generator signature against ``pubkey`` (RK-1.2)."""
        return verify(self.canonical_bytes(), self.generator_signature, pubkey)

    def verify_environment(self, sandbox_pubkey: bytes) -> bool:
        """Verify the environment signature against ``sandbox_pubkey`` (RK-3.1)."""
        if not self.environment_signature:
            return False
        return verify(
            self.canonical_bytes(), self.environment_signature, sandbox_pubkey
        )

    def verify_antilazy(self, alm_pubkey: bytes) -> bool:
        """Verify the anti-lazy signature against ``alm_pubkey`` (AL-1.1)."""
        if not self.antilazy_signature:
            return False
        return verify(self.canonical_bytes(), self.antilazy_signature, alm_pubkey)


def make_rootknot(
    key: SessionKey,
    workspace_path: str,
    artifact_digest: Digest,
    assumption_digest: Digest,
    model_name: str = "unknown",
    model_version: str = "0",
    plan_id: PlanId | None = None,
    step_id: StepId | None = None,
    parent_digests: tuple[Digest, ...] = (),
) -> Rootknot:
    """Construct and sign a v1 (v0.3-compatible) Rootknot."""
    session_id = key.public_key_id()[:16]
    generator = GeneratorRef(
        model_name=model_name,
        model_version=model_version,
        session_id=session_id,
        public_key_id=key.public_key_id(),
    )
    return Rootknot(
        plan_id=plan_id or make_plan_id(),
        step_id=step_id or make_step_id(),
        assumption_digest=assumption_digest,
        generator=generator,
        parent_digests=parent_digests,
        workspace_path=workspace_path,
        artifact_digest=artifact_digest,
        created_at_ns=time.time_ns(),
        generator_signature=b"",
        schema_version=1,
    ).sign(key)


def make_rootknot_v2(
    *,
    key: SessionKey,
    sandbox_signer,  # type: ignore[no-untyped-def]
    workspace_path: str,
    artifact_digest: Digest,
    assumption_digest: Digest,
    acceptance_suite_digest: Digest,
    predicate_results: tuple[Digest, ...],
    manifest_digest: Digest,
    model_name: str = "unknown",
    model_version: str = "0",
    plan_id: PlanId | None = None,
    step_id: StepId | None = None,
    parent_digests: tuple[Digest, ...] = (),
) -> Rootknot:
    """Construct, sign, and environment-attest a v2 (v0.4) Rootknot.

    ``sandbox_signer`` is a ``ract.security.keys.SandboxKey`` (or any
    object with the same ``sign(bytes) -> bytes`` surface). The returned
    Rootknot carries both the generator signature and the environment
    signature — RK-3 requires both.
    """
    session_id = key.public_key_id()[:16]
    generator = GeneratorRef(
        model_name=model_name,
        model_version=model_version,
        session_id=session_id,
        public_key_id=key.public_key_id(),
    )
    unsigned = Rootknot(
        plan_id=plan_id or make_plan_id(),
        step_id=step_id or make_step_id(),
        assumption_digest=assumption_digest,
        generator=generator,
        parent_digests=parent_digests,
        workspace_path=workspace_path,
        artifact_digest=artifact_digest,
        created_at_ns=time.time_ns(),
        generator_signature=b"",
        environment_signature=b"",
        acceptance_suite_digest=acceptance_suite_digest,
        predicate_results=tuple(predicate_results),
        manifest_digest=manifest_digest,
        schema_version=2,
    )
    return unsigned.sign(key).attest_environment(sandbox_signer)


def make_rootknot_v3(
    *,
    key: SessionKey,
    sandbox_signer,  # type: ignore[no-untyped-def]
    alm_signer,  # type: ignore[no-untyped-def]
    workspace_path: str,
    artifact_digest: Digest,
    assumption_digest: Digest,
    acceptance_suite_digest: Digest,
    predicate_results: tuple[Digest, ...],
    manifest_digest: Digest,
    gate_results: tuple[GateResult, ...],
    reversal_taint: ReversalTaint = "clean",
    model_name: str = "unknown",
    model_version: str = "0",
    plan_id: PlanId | None = None,
    step_id: StepId | None = None,
    parent_digests: tuple[Digest, ...] = (),
) -> Rootknot:
    """Construct, sign, and triple-attest a v3 (v0.4 ALM) Rootknot.

    All three signatures land: generator (session key), environment
    (sandbox signer), and anti-lazy (ALM verifier signer). The returned
    Rootknot verifies under RK-1, RK-2, RK-3, and AL-1 when the pubkeys
    the verifier resolves match the keys used here.
    """
    session_id = key.public_key_id()[:16]
    generator = GeneratorRef(
        model_name=model_name,
        model_version=model_version,
        session_id=session_id,
        public_key_id=key.public_key_id(),
    )
    unsigned = Rootknot(
        plan_id=plan_id or make_plan_id(),
        step_id=step_id or make_step_id(),
        assumption_digest=assumption_digest,
        generator=generator,
        parent_digests=parent_digests,
        workspace_path=workspace_path,
        artifact_digest=artifact_digest,
        created_at_ns=time.time_ns(),
        generator_signature=b"",
        environment_signature=b"",
        acceptance_suite_digest=acceptance_suite_digest,
        predicate_results=tuple(predicate_results),
        manifest_digest=manifest_digest,
        antilazy_signature=b"",
        gate_results=tuple(gate_results),
        reversal_taint=reversal_taint,
        schema_version=3,
    )
    return (
        unsigned.sign(key)
        .attest_environment(sandbox_signer)
        .attest_antilazy(alm_signer)
    )


# RACT 0.4.0
