# RACT Provenance and Separation Statement

RACT is independent of any private system, and every artifact it writes is
cryptographically bound to its origin. This document points at commands and
source symbols rather than prose.

## What a Rootknot attests

Every file the recursion loop writes carries a **Rootknot** — a signed
provenance capability (`src/ract/core/rootknot.py`, `Rootknot`). A Rootknot
binds an artifact to six things:

- the **plan step** that produced it (`plan_id`, `step_id`),
- the **assumption** that justified the step (`assumption_digest`),
- the **generator** that authored it (`GeneratorRef`: model name/version,
  session id, public key id),
- the **parent artifacts** it derives from (`parent_digests`, a DAG),
- the **artifact digest** (`artifact_digest`, SHA-256 of the artifact bytes),
- and an **ed25519 signature** over the canonical serialization of all the
  above (`signature`, 64 bytes).

The signature is produced by `Rootknot.sign(key)` and checked by
`Rootknot.verify(pubkey)`. The signing primitive is `cryptography`'s ed25519
(`src/ract/core/keys.py`, `SessionKey`), a public, audited library. There is
no proprietary crypto anywhere in the chain.

**Extended attestations (v0.4).** v0.4 substrate sidecars add
`environment_signature`, `acceptance_suite_digest`, `predicate_results`,
`manifest_digest` (RK-3); v0.4-ALM adds `antilazy_signature`, `gate_results`,
`reversal_taint` (AL-1). Both extend the same signed binding; see the
Sidecar schemas table below.

## How RACT stays independent of private systems

RACT depends only on its declared, public dependencies (`pyproject.toml`):
`pyyaml`, `httpx`, `zstandard`, `rich`, and `cryptography`.

- **No proprietary code.** `src/ract/` imports nothing private. The lint
  test `tests/test_public_provenance.py` fails the build on a forbidden
  import.
- **No private endpoints.** Providers are configured in `ract.yaml`; the
  default `local` adapter points at `127.0.0.1`.
- **No shared state.** All runtime state lives under the operator's XDG
  state directory or the workspace's gitignored `.rack/`. Nothing leaves
  the machine.

## How to verify a Rootknot without the tool

Each indexed artifact is stored two ways: a SQLite index at
`.rack/rootknots.db` in the workspace root (`ProvenanceIndex`,
`src/ract/core/provenance.py`) and a sidecar file
`.<artifact>.rootknot.json` beside the artifact.

To verify by hand: read the sidecar, recompute the canonical bytes as
`Rootknot.canonical_bytes()` does (sorted JSON, `(",", ":")` separators),
and check the ed25519 signature against the generator's public key. The
CLI verb

```
ract provenance verify <path>
```

automates this: loads the sidecar, recomputes the artifact digest,
resolves the generator's public key from the local key store (including
archived keys), checks the signature, and prints `valid` / `invalid`
with exit code 0 / 1. Session public keys live in `<state_dir>/ract/keys/*.pem`.

## What happens if a Rootknot is missing or invalid

Before every recursion step, `verify_workspace(...)` checks three invariants
across every indexed artifact (`src/ract/core/provenance.py`):

- **RK-1** — the artifact exists, its digest matches, the generator signature
  verifies, the plan and step are active, the assumption is registered, and
  every parent digest resolves recursively (RK-1.1 through RK-1.6).
- **RK-2** — the assumption behind every rootknot is active or discharged; a
  violated assumption marks dependent rootknots stale.
- **RK-3 (Environmental Attestation, v0.4)** — for every v2 sidecar: the
  environment signature verifies under the run's sandbox pubkey (RK-3.1);
  the `acceptance_suite_digest` is a currently registered suite (RK-3.2);
  the `predicate_results` tuple is non-empty (RK-3.3); the `manifest_digest`
  is a currently registered manifest (RK-3.4).
- **AL-1 (Anti-Lazy Attestation, v0.4-ALM)** — for every v3 sidecar: the
  anti-lazy signature verifies under the ALM verifier pubkey the
  resolver returns (AL-1.1); every `GateResult` in `gate_results` has
  `passed=True` OR carries a `handshake_id` that appears in the
  operator's approved-handshake set (AL-1.2); `reversal_taint` is
  `"clean"` OR the run's `plan_id` appears in the operator's
  `accepted_partial_taint_runs` set (AL-1.3).

If any fails, the loop halts immediately with
`TerminationCause.PROVENANCE_FAILURE` (T3) and names the sub-clause that
tripped. It does not continue, does not write further artifacts, and does
not silently repair.

## Sidecar schemas (v0.4)

Reader dispatches on the top-level `schema` field.

- **`sidecar/v1`** (v0.3) — no `schema` field. Carries `signature`.
  RK-3 skipped with `DeprecationWarning`; `--strict` refuses.
- **`sidecar/v2`** (v0.4 substrate) — `schema: sidecar/v2`. Adds
  `generator_signature`, `environment_signature`,
  `acceptance_suite_digest`, `predicate_results`, `manifest_digest`.
- **`sidecar/v3`** (v0.4 ALM) — `schema: sidecar/v3`. Adds
  `antilazy_signature`, `gate_results` (tuple of eight per-gate
  records), `reversal_taint` (`"clean"` or `"partial"`), and the
  base64 raw ALM verifier pubkey (`alm_pubkey_b64`) so AL-1 can be
  verified from the sidecar plus an out-of-sidecar registry check.

**Offline verification.** v2 sidecars embed `sandbox_pubkey_b64` for
RK-3.1; v3 sidecars also embed `alm_pubkey_b64` for AL-1.1; save sites
may embed `generator_pubkey_b64`. Recompute canonical bytes,
ed25519-verify against embedded pubkeys, check digest fields against
the registered set.

**Authorship bound.** The sidecar proves its own consistency. Whether
the embedded pubkeys are the ones the operator expected is out-of-band
work. The v0.4-ALM design REQUIRES cross-checking the ALM verifier
pubkey against `.rack/alm/archive/` or an operator registry (see
ADR-0023).

| Sidecar | RK-1 | RK-2 | RK-3 | AL-1 | `--strict` |
|---|---|---|---|---|---|
| `sidecar/v1` | required | required | skipped (warn) | skipped (warn) | refused |
| `sidecar/v2` | required | required | required | skipped (warn) | refused |
| `sidecar/v3` | required | required | required | required | required |

<!-- RACT 0.4.0 -->
