# RACT Provenance and Separation Statement

RACT is independent of any private system, and every artifact it writes is
cryptographically bound to its origin. This document is the single public
statement of how both claims hold. It is intentionally short and points at
commands and source symbols rather than prose.

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
(`src/ract/core/keys.py`, `SessionKey`) — a public, audited library. There is
no proprietary crypto anywhere in the chain.

## How RACT stays independent of private systems

RACT depends only on its declared, public dependencies (`pyproject.toml`):
`pyyaml`, `httpx`, `zstandard`, `rich`, and `cryptography`. Specifically:

- **No proprietary code.** `src/ract/` imports nothing from a private or
  internal package. The lint test `tests/test_public_provenance.py` asserts
  this and fails the build if a forbidden import appears.
- **No private endpoints.** Providers are configured by the operator in
  `ract.yaml`; the default `local` adapter points at `127.0.0.1`. RACT ships
  no hardcoded call to any private host.
- **No shared state.** All runtime state — session keys, the provenance index,
  approval queues — lives under the operator's XDG state directory
  (`%LOCALAPPDATA%\ract\` on Windows, `$XDG_STATE_HOME/ract/` elsewhere) or in
  the workspace's gitignored `.rack/` directory. Nothing leaves the machine.

## How to verify a Rootknot without the tool

Each indexed artifact is stored two ways:

1. **SQLite index** — `.rack/rootknots.db` in the workspace root; the runtime
   source of truth (`ProvenanceIndex`, `src/ract/core/provenance.py`).
2. **Sidecar file** — `.<artifact>.rootknot.json` beside the artifact; the
   human-audit path. It carries the canonical fields and the hex-encoded
   signature.

To verify by hand: read the sidecar, recompute the canonical bytes exactly as
`Rootknot.canonical_bytes()` does (sorted JSON, `(",", ":")` separators), and
check the ed25519 signature against the generator's public key. The CLI verb

```
ract provenance verify <path>
```

automates this: it loads the sidecar, recomputes the artifact digest, resolves
the generator's public key from the local key store (including archived keys,
so pre-rotation rootknots still verify), checks the signature, and prints
`valid` / `invalid` with exit code 0 / 1.

The operator's session public keys live in `<state_dir>/ract/keys/*.pem`.

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

If any fails, the loop halts immediately with
`TerminationCause.PROVENANCE_FAILURE` (T3) and names the sub-clause that
tripped. It does not continue, does not write further artifacts, and does
not silently repair.

## Sidecar schemas (v0.4)

Reader dispatches on the top-level `schema` field.

- **`sidecar/v1`** (v0.3) — no `schema` field. Carries `signature`.
  RK-3 skipped with `DeprecationWarning`; `--strict` refuses.
- **`sidecar/v2`** (v0.4) — `schema: sidecar/v2`. Adds
  `generator_signature`, `environment_signature`,
  `acceptance_suite_digest`, `predicate_results`, `manifest_digest`.

**Offline verification.** v2 sidecars embed the raw sandbox pubkey
(`sandbox_pubkey_b64`, 32 bytes base64) so RK-3.1 checks without any
local `.rack/` state. Save sites may also embed `generator_pubkey_b64`.
The sidecar becomes a self-contained audit artifact: recompute
canonical bytes, ed25519-verify against embedded pubkeys, check digest
fields against the registered set.

**Authorship bound.** The sidecar proves its own *consistency* —
signatures verify against embedded pubkeys, digests match, bytes are
reproducible. Whether those pubkeys are the ones the operator expected
is out-of-band work: compare the embedded values against known-good
keys.

| Sidecar | RK-1 | RK-2 | RK-3 | `--strict` |
|---|---|---|---|---|
| `sidecar/v1` | required | required | skipped (warn) | refused |
| `sidecar/v2` | required | required | required | required |

<!-- RACT 0.4.0 -->
