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

import time
import warnings
from dataclasses import dataclass, field
from typing import Literal

from ract.canonical import dumps_jcs
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
    # v0.5.0 memory discipline (module_09): optional retrieval-bundle
    # attestation. When non-``None`` this is the SHA-256 of the
    # retrieval bundle the step's model call consumed (see
    # ``ract.memory.retrieve.RetrievalBundle`` -> the digest is the
    # ``bundle_digest`` helper below). The field is BACKWARD-COMPATIBLE:
    # older v1/v2/v3 sidecars without the field verify unchanged
    # because canonical_bytes() only includes ``retrieval_attestation``
    # when it is set. See ADR-0040 and the sacred-spine test
    # ``test_older_sidecar_still_verifies``.
    retrieval_attestation: Digest | None = None
    # v0.5.1 external-review response (module_02): three OPT-IN
    # canonical-bytes extensions binding the Rootknot to the workspace
    # state, the operator prompt, and the run identifier that produced
    # it. The spec calls the payload family SCHEMA_VERSION 2 (versus
    # SCHEMA_VERSION 1 for the v0.5.0 baseline); in the code-level
    # dispatch this is instance ``schema_version == 4`` (existing
    # values 1/2/3 remain reserved for v0.3 / v0.4-substrate / v0.4-ALM
    # payload shapes). Each field is BACKWARD-COMPATIBLE: v1/v2/v3
    # sidecars produced without them hash byte-identically to the
    # v0.5.0 baseline because ``canonical_bytes()`` only emits each
    # field when it is set (same pattern module_09's
    # ``retrieval_attestation`` established). ``run_id`` is an empty
    # string (not ``None``) so the field type stays simple; the guard
    # is a truthy check. See
    # ``docs/RACT_v0.5.1_EXTERNAL_REVIEW_RESPONSE_SPEC.md`` §4
    # module_02 and the regression tests
    # ``tests/unit/test_canonical_bytes_v2.py``,
    # ``tests/unit/test_schema_version_backread.py``,
    # ``tests/unit/test_workspace_digest_ancestor.py``.
    workspace_digest: Digest | None = None
    prompt_digest: Digest | None = None
    run_id: str = ""

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
        # v0.5.0 memory discipline (module_09): retrieval_attestation is
        # OPT-IN. It appears in the canonical bytes ONLY when it is set,
        # so a sidecar produced before this field existed (or a v3
        # constructor that does not pass the field) verifies unchanged
        # under the schema-version dispatch above. The field is a
        # trailing addition to the sorted-key payload; the sort-key
        # position ("retrieval_attestation" > "reversal_taint" > ...)
        # is deterministic under ``ract.canonical.dumps_jcs()`` (RFC
        # 8785 JCS -- codepoint-sorted keys, NFC-normalised strings,
        # strict-JSON floats). v0.5.1 module_03 replaced the legacy
        # ``json.dumps(sort_keys=True)`` serialiser with JCS; the
        # sort order is unchanged on the ASCII path.
        if self.retrieval_attestation is not None:
            payload["retrieval_attestation"] = self.retrieval_attestation.hex()
        # v0.5.1 module_02: three OPT-IN payload extensions. Each is
        # emitted ONLY when set, so a v1/v2/v3 knot constructed without
        # them produces byte-identical canonical bytes to the v0.5.0
        # baseline (backward-read invariant; see
        # ``test_schema_version_backread``). Sort-key placement is a
        # property of the canonical serialiser: the three keys land
        # alphabetically after ``predicate_results`` /
        # ``retrieval_attestation`` / ``reversal_taint`` without
        # per-key ordering logic.
        if self.workspace_digest is not None:
            payload["workspace_digest"] = self.workspace_digest.hex()
        if self.prompt_digest is not None:
            payload["prompt_digest"] = self.prompt_digest.hex()
        if self.run_id:
            payload["run_id"] = self.run_id
        # v0.5.1 module_03: sacred-spine serialiser is now RFC 8785
        # JCS. Byte output is cross-Python-version deterministic
        # (NFC-normalised, strict floats, codepoint-sorted keys),
        # closing REVIEW_4_UNKNOWN §D2 (canonical JSON flaw). The
        # payload shape is unchanged from module_02; the byte
        # sequence for existing test fixtures shifts only where the
        # v0.5.0 stdlib ``json.dumps`` output was already JCS-equal
        # (which for these ASCII-key payloads is byte-identical).
        return dumps_jcs(payload)

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
            retrieval_attestation=self.retrieval_attestation,
            workspace_digest=self.workspace_digest,
            prompt_digest=self.prompt_digest,
            run_id=self.run_id,
        )

    def attest_environment(self, sandbox_signer) -> Rootknot:  # type: ignore[no-untyped-def]
        """Return a new Rootknot whose ``environment_signature`` is set.

        ``sandbox_signer`` is any object with a ``sign(bytes) -> bytes``
        method — typically a ``ract.security.keys.SandboxKey`` (see
        module_06 step 3). The environment signature is over the same
        canonical bytes as the generator signature; RK-3 verifies both
        under distinct pubkeys.

        v0.5.1 module_07 (Historical Manifest Ledger): after signing,
        the fresh knot is offered to the ambient
        :class:`ract.security.manifest_ledger.ManifestLedger` (bound
        via :func:`ract.security.manifest_ledger.bind_ledger`). The
        ledger observer is a NO-OP when no ledger is bound (test
        fixtures, v1/v2/v3 knots, or callers that opt out by not
        binding). The signed payload is unchanged -- the ledger is a
        pure observer, not part of the RK-3 signed bytes.
        """
        signed = Rootknot(
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
            retrieval_attestation=self.retrieval_attestation,
            workspace_digest=self.workspace_digest,
            prompt_digest=self.prompt_digest,
            run_id=self.run_id,
        )
        # module_07 observer: the ledger consumes the freshly signed
        # knot and appends an entry when an ambient ledger is bound.
        # The local import breaks the security<-core cycle at import
        # time (security.manifest_ledger already imports from core).
        # SP Q5 amendment: the observer helper handles its own append
        # failures internally (WARN + manifest.ledger.refused event);
        # we still guard against exotic import-time / TypeError paths
        # so a malformed installation cannot invalidate a signed knot.
        try:
            from ract.security.manifest_ledger import (
                record_environment_attestation,
            )

            record_environment_attestation(signed)
        except Exception:  # noqa: BLE001 -- ledger failure never invalidates a signed knot
            import logging

            logging.getLogger("ract.core.rootknot").debug(
                "manifest_ledger observer import or dispatch failed",
                exc_info=True,
            )
        return signed

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
            retrieval_attestation=self.retrieval_attestation,
            workspace_digest=self.workspace_digest,
            prompt_digest=self.prompt_digest,
            run_id=self.run_id,
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
    retrieval_attestation: Digest | None = None,
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
        retrieval_attestation=retrieval_attestation,
    )
    return (
        unsigned.sign(key)
        .attest_environment(sandbox_signer)
        .attest_antilazy(alm_signer)
    )


def make_rootknot_v4(
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
    workspace_digest: Digest,
    prompt_digest: Digest,
    run_id: str | None = None,
    reversal_taint: ReversalTaint = "clean",
    model_name: str = "unknown",
    model_version: str = "0",
    plan_id: PlanId | None = None,
    step_id: StepId | None = None,
    parent_digests: tuple[Digest, ...] = (),
    retrieval_attestation: Digest | None = None,
) -> Rootknot:
    """Construct, sign, and triple-attest a v4 (v0.5.1 external-review) Rootknot.

    Extends :func:`make_rootknot_v3` with the three canonical-bytes
    additions from module_02: ``workspace_digest`` (binds the payload
    to the workspace state), ``prompt_digest`` (binds it to the
    operator's compile-time intent text), and ``run_id`` (a stable
    identifier propagated through every artifact + Rootknot + WAL
    entry + trace event in a run). All three ride INSIDE the signed
    canonical bytes, so the three signatures (generator / environment
    / anti-lazy) all attest over them.

    The spec calls this payload family SCHEMA_VERSION 2 (v0.5.0 was
    SCHEMA_VERSION 1). At the code level the instance ``schema_version``
    is 4 — values 1/2/3 remain reserved for v0.3 / v0.4-substrate /
    v0.4-ALM payload shapes; 4 marks the v0.5.1 extension. A v0.5.0
    verifier dispatching on ``schema_version`` sees unknown value 4
    and halts loudly rather than silently trusting under-attested
    bytes (see ``test_schema_version_backread``).

    All three new fields are REQUIRED at construction: the whole
    point of v4 is that the signed payload binds them, so passing
    ``None`` or empty string would defeat the purpose. Callers that
    do not have all three should use ``make_rootknot_v3`` instead
    (which keeps the fields absent and hashes byte-identically to
    v0.5.0 payloads).

    See ``docs/RACT_v0.5.1_EXTERNAL_REVIEW_RESPONSE_SPEC.md`` §4
    module_02 and
    ``_BUILD/ract_v0.5.1_external_review_response/module_02.md``.
    """
    if workspace_digest is None:
        raise ValueError("make_rootknot_v4 requires workspace_digest")
    if prompt_digest is None:
        raise ValueError("make_rootknot_v4 requires prompt_digest")
    # v0.5.1 module_06: run_id resolution -- explicit kwarg wins; when
    # ``None``, fall back to the ambient
    # :func:`ract.runtime.get_current_run_id`. The invariant that
    # every v4 knot carries a non-empty ``run_id`` is preserved --
    # callers with neither an explicit id nor an ambient one still
    # trip the ValueError, matching the module_02 contract.
    if not run_id:
        from ract.runtime import get_current_run_id

        run_id = get_current_run_id() or ""
    if not run_id:
        raise ValueError(
            "make_rootknot_v4 requires a non-empty run_id; pass explicitly "
            "or bind one via ract.runtime.bind_run_id() before calling"
        )
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
        schema_version=4,
        retrieval_attestation=retrieval_attestation,
        workspace_digest=workspace_digest,
        prompt_digest=prompt_digest,
        run_id=run_id,
    )
    return (
        unsigned.sign(key)
        .attest_environment(sandbox_signer)
        .attest_antilazy(alm_signer)
    )


def bundle_digest(bundle_bytes: bytes) -> Digest:
    """Return the SHA-256 :class:`Digest` of a retrieval bundle's bytes.

    Module_09 helper. Callers hash the canonical projection of a
    :class:`~ract.memory.retrieve.RetrievalBundle` (e.g. via
    :func:`ract.memory.retrieve.bundle_to_cache_payload` +
    :func:`ract.canonical.dumps_jcs`) and pass the resulting bytes
    to this helper to build the ``retrieval_attestation`` value that
    :func:`make_rootknot_v3` binds into the signed canonical bytes.
    v0.5.1 module_03 replaced the legacy
    ``json.dumps(sort_keys=True)`` canonicalisation with RFC 8785
    JCS; the digest input for retrieval bundles now routes through
    ``dumps_jcs`` on the memory-side migration path.

    Kept as a small, dependency-free helper so
    :mod:`ract.core.rootknot` does NOT import
    :mod:`ract.memory.retrieve` — the sacred spine stays independent
    of the memory-discipline layer.
    """
    import hashlib

    return Digest(hashlib.sha256(bundle_bytes).digest())


# RACT 0.5.1
