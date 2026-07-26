# ADR-0016 — Rootknot re-oriented from author-attestation to environment-attestation

## Status

Accepted (v0.4.0, module_06).

## Context

The v0.3 ``Rootknot`` (see ``src/ract/core/rootknot.py``, REBUILD spec
§3) bound an artifact to the *generator* that authored it. The
``generator_signature`` (v0.3 ``signature``) was the sole
provenance signature; a Rootknot's trust flowed *from the author*. The
SUBSTRATE spec §7 critiques this direction: an agent-authored artifact
attested only by the agent is a self-signed capability. The trust must
flow *from the environment* — the sandbox, the acceptance suite, the
capability manifest — because those are the things the operator
controls end-to-end.

## Decision

Extend ``Rootknot`` (module_06 step 2) with four new fields:

- ``environment_signature: bytes`` — ed25519 by a per-run sandbox key
  (``ract.security.keys.SandboxKey``).
- ``acceptance_suite_digest: Digest`` — SHA256 of the
  ``AcceptanceSuite`` frozen for this run (see module_01).
- ``predicate_results: tuple[Digest, ...]`` — SHA256 of each
  ``PredicateResult`` that gated this rootknot's write (see
  module_01).
- ``manifest_digest: Digest`` — SHA256 of the ``CapabilityManifest``
  in force at write time (see module_03).

The old ``signature`` field is renamed to ``generator_signature``. A
deprecated ``@property`` alias named ``signature`` continues to work
under v0.3 callers with a ``DeprecationWarning``; scheduled for removal
in v0.5.

A new invariant, **RK-3 (Environmental Attestation)**, is added to
``verify_workspace``. RK-3 requires the environment signature to verify
under the sandbox pubkey, the acceptance suite digest and manifest
digest to be currently registered, and the predicate result tuple to
be non-empty. v0.3 (v1) sidecars are dispatched to skip RK-3 with a
``DeprecationWarning``; ``verify --strict`` refuses them.

Trust direction under v0.4: the *environment* is the primary attester
(sandbox key), the *generator* is a secondary co-signer whose
signature proves the author of the payload without granting it
authority. A rootknot without a valid environment signature is not a
rootknot; it is unsanctioned output.

## Rejected alternatives

1. **Keep the single generator signature (v0.3 baseline).** Rejected
   — does not answer the trust-direction critique in SUBSTRATE §7. A
   self-signed capability is not evidence that the environment
   accepted the write; it is only evidence that the generator wrote
   it. The whole point of a substrate-first rebuild is to move the
   trust anchor.
2. **Require an author signature and refuse unsigned artifacts.**
   Rejected — this repositions *author identity* as a mechanism.
   SUBSTRATE §7 explicitly refuses author identity as an invariant:
   provenance must be verifiable without knowing (or trusting) who
   the author is. A well-known author signing badly is a worse story
   than an anonymous environment-signed artifact whose predicates
   passed.

## Consequences

- v2 sidecars (``schema: sidecar/v2``) embed the raw sandbox pubkey
  in base64 so verification is offline-possible from the sidecar
  alone plus stdlib crypto. This subsumes the v0.3.1-hardening
  flagged item on self-contained sidecars (`_BUILD/ract_v0.3.1_hardening/module_02.md`).
- v1 sidecars (v0.3) continue to verify under RK-1 + RK-2 only during
  the migration window; RK-3 skips with a ``DeprecationWarning``.
  ``verify --strict`` refuses them outright.
- Sandbox private key material is written under
  ``.rack/sandbox/<run_id>.key`` and archived to
  ``.rack/sandbox/archive/`` on run completion. The private material
  never leaves the sandbox process; the model layer sees only the
  public key.

## Reference sources

- SUBSTRATE spec §7 (The Trust-Direction Fix, Rootknot Preserved).
- REBUILD spec §3 (Rootknot Made Real) — the v0.3 baseline this
  extends.
- RFC 8032 (Ed25519 signatures).
- ``cryptography`` Python library public docs (``https://cryptography.io/``).
- v0.3.1 hardening precedent for self-contained sidecars
  (``_BUILD/ract_v0.3.1_hardening/module_02.md``), subsumed here.

<!-- RACT 0.4.0 -->
