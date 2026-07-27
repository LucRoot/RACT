# ADR-0023 — Three-signature Rootknot with Invariant AL-1 plus sycophancy circuit breaker plus Investigator pre-completion contract

Status: accepted (v0.4.0-rc1, ALM pipeline module_05).

## Context

The substrate `Rootknot` (RACT §7, v0.4 substrate module_06) carries two
signatures already: the generator signature (session key) and the
environment signature (sandbox key, RK-3). RK-3 attests that the
artifact was produced inside the sandbox the operator provisioned.

The ALM specification (§5, §10) requires a third signature on top of
RK-3: an *anti-lazy attestation* by a separate ALM verifier key. AL-1
binds an artifact not just to a generator and an environment but to a
completion the anti-lazy gates approved.

ALM §4 (Sycophancy Circuit Breaker) and §8 (Investigator) name two
mechanisms that must be present in the loop before AL-1 is credible: a
reversal detector that catches assistant turns that flip position
without new evidence, and an Investigator that reads files the primary
loop did not touch. Both feed the completion invariant AL-1 encodes.

The three surfaces ship together in one module because AL-1 is the
place where each mechanism's output is signed into the rootknot.

## Decision

1. Rootknot gains three fields — `antilazy_signature`, `gate_results`,
   `reversal_taint`. `schema_version` bumps to 3. `canonical_bytes`
   dispatches on the version so v1 (v0.3) and v2 (v0.4 substrate)
   signatures continue to verify.
2. A new signing key type, `AlmVerifierKey`, mirrors `SandboxKey`. The
   ALM verifier process holds it; it is distinct from the sandbox key
   so compromising one does not forge the other.
3. Sidecar `schema: sidecar/v3` embeds the sandbox pubkey AND the ALM
   verifier pubkey (both base64). Offline verify from the sidecar
   alone is possible for RK-1, RK-2, RK-3, and AL-1.
4. `verify_workspace` implements **Invariant AL-1 (Anti-Lazy
   Attestation)** with three sub-clauses per rootknot:
   - AL-1.1 `knot.antilazy_signature` verifies under the ALM pubkey.
   - AL-1.2 every `GateResult` is PASS or has a `handshake_id` that
     appears in the `approved_gate_exceptions` set the operator's
     `HandshakeRegistry` produced.
   - AL-1.3 `reversal_taint == "clean"` OR the run appears in
     `accepted_partial_taint_runs`.
5. The sycophancy circuit is a deterministic regex-plus-heuristic
   classifier (`ract.antilazy.sycophancy`). Two consecutive suspicious
   reversals fire the forcing prompt (`force_evidence_or_restore`);
   unresolved suspicious reversals taint the run.
6. The Investigator (`ract.antilazy.investigator`) selects up to 20
   untouched files ranked by symbol-graph adjacency (import + call
   edges) to touched symbols. It runs a companion-provider probe on
   each and emits `investigator.report`. A completion without the
   report emits `laziness.violated` with `kind="investigator_missing"`.

## Chain of custody for the ALM pubkey

The v3 sidecar embeds the ALM pubkey the sidecar's `antilazy_signature`
was produced under. This is trust-by-declaration: an attacker who
forges the sidecar controls both the signature and the pubkey it
verifies against. **The design decision this ADR makes is that the
verifier is REQUIRED to cross-check the embedded pubkey against an
out-of-sidecar source.** The v0.4.0-rc1 shape of that source is a
resolver passed as `alm_pubkey` to `verify_workspace` — typically a
lookup into the workspace-level `.rack/alm/archive/*.key` file the ALM
verifier process wrote at run close, or an operator-supplied registry.

The v3 sidecar's `alm_pubkey_b64` field is a convenience for offline
verify when no registry is available, but such verification is
explicitly trust-by-declaration and is documented as such (see the
`load_sidecar_alm_pubkey` docstring). The registry check is the
authoritative path.

## Rejected alternatives

- **Single-signature rootknot.** Loses environmental attestation and
  loses anti-lazy attestation. Every artifact would carry only the
  generator's claim, which the substrate spec already ruled out at
  module_06.
- **Two-signature rootknot (no ALM).** Preserves RK-3 but ships no
  attestation that the anti-lazy gates ran. Under partial-day operator
  workflows, an artifact could bypass the sycophancy circuit and the
  Investigator entirely and still verify under RK-1..RK-3. AL-1 exists
  to close that.
- **Sycophancy detection as a model-based classifier.** The model
  grades its own homework. A regex-plus-heuristic classifier is
  weaker on subtle reversals ("actually I want to reconsider") but is
  independent — its false-negative rate is the acceptable cost of
  independence. The two-consecutive-reversal gate handles regex noise.
  A model-assisted second-pass is a flagged gap.
- **Investigator scheduled by the primary model.** Defeats the
  independence the Investigator is supposed to attest. The Investigator
  is scheduled by the loop, not by the model; its file selection is a
  deterministic top-K heuristic; its probe is a companion provider
  from a different family per G7's constraint.
- **`reversal_taint` as boolean.** Loses the operator handshake
  flexibility for accepted-partial runs. The `partial` value paired
  with `accepted_partial_taint_runs` gives the operator a
  point-in-time acceptance path without erasing the taint record.

## Consequences

- v0.4.0-rc1 artifacts carry three signatures. Any workspace signed
  before this module lands (v1 or v2 sidecars) continues to verify
  under the compatibility reader; under `strict=True` v0.4-ALM
  refuses them (the bar rises the same way RK-3 raised it in
  module_06).
- The Investigator is a pre-completion contract, not an advisory. A
  completion without its report is unauthenticated.
- Partial-taint runs need an operator decision. When there is none,
  the workspace does not verify under `--strict` and the artifact
  cannot be shipped as attested.

## References

- ALM spec §4, §5, §8, §10.
- SUBSTRATE spec §7 (Rootknot preserved; trust direction inverted).
- RFC 8032 (Ed25519).
- `ract.security.keys.SandboxKey` (the shape `AlmVerifierKey` mirrors).
