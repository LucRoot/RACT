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
check the ed25519 signature against the generator's public key. The
**planned** CLI verb `ract provenance verify <path>` (v0.3.0) automates this
and prints `valid` / `invalid`.

The operator's session public keys live in `<state_dir>/ract/keys/*.pem`.

## What happens if a Rootknot is missing or invalid

Before every recursion step, `verify_workspace(...)` checks two invariants
across every indexed artifact (`src/ract/core/provenance.py`):

- **RK-1** — the artifact exists, its digest matches, the signature verifies,
  the plan and step are active, the assumption is registered, and every
  parent digest resolves recursively (RK-1.1 through RK-1.6).
- **RK-2** — the assumption behind every rootknot is active or discharged; a
  violated assumption marks dependent rootknots stale.

If either fails, the loop halts immediately with
`TerminationCause.PROVENANCE_FAILURE` (T3). It does not continue, does not
write further artifacts, and does not silently repair. A tampered artifact,
a missing parent, a bad signature, or a violated assumption all produce the
same halt.

<!-- RACT 0.3.0 -->
