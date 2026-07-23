# ADR-0001: Provenance-Anchored Artifacts via Signed Rootknots

## Status

Accepted

## Context

RACT produces files during a recursive agent loop. In v0.1.x the only provenance mechanism was the `_ROOT_KNOT = object()` sentinel: every non-init Python file had to carry it, and the loop stopped if a file was missing the sentinel. This was a presence check, not a cryptographic one. It bound artifacts to an author string but not to the plan step, assumption, generator, or parent artifacts that produced them. A senior-architect review flagged this as a category error: a sentinel is not an invariant.

We needed a mechanism that:

- cryptographically binds each artifact to its producing step and assumption,
- allows a third party to verify the binding without running RACT,
- supports a DAG of parent artifacts,
- stores metadata separately from artifact content so neither invalidates the other,
- works on Windows, macOS, and Linux without elevated privileges.

## Decision

Introduce a signed provenance capability called a **Rootknot**.

Every artifact the loop writes carries a `Rootknot` dataclass containing:

- `plan_id` and `step_id` (16-byte UUIDs),
- `assumption_digest` (SHA256 of the justifying assumption),
- `generator` (`GeneratorRef` with model name/version, session id, and public key id),
- `parent_digests` (SHA256 of the canonical bytes of upstream rootknots),
- `workspace_path`, `artifact_digest` (SHA256 of artifact bytes),
- `created_at_ns`, and a 64-byte ed25519 signature.

The signature covers the canonical JSON serialization of every field except `signature`. Rootknots are stored in a workspace-wide SQLite index at `.rack/rootknots.db` and in optional sidecar files named `.<artifact>.rootknot.json`. The SQLite index is the runtime source of truth; sidecars exist for human audit and external tooling.

`verify_workspace(state)` checks two invariants before every recursion step:

- **RK-1:** for every indexed artifact, the file exists, its digest matches, the signature verifies, the plan/step are active, the assumption is registered, and every parent digest resolves recursively.
- **RK-2:** the assumption behind every rootknot is either active or discharged; a violated assumption marks dependent rootknots stale and halts the loop with cause T3.

The old `_ROOT_KNOT` sentinel is kept as a legacy marker for v0.2.0 and will be removed in v0.3.0.

## Consequences

- Every artifact becomes independently auditable.
- The loop can detect tampering, missing parents, and assumption violations structurally.
- Workspace I/O grows by one SQLite write and one sidecar write per artifact; WAL mode keeps this cheap.
- Session keys must be persisted securely; we store ed25519 private keys in XDG state (`%LOCALAPPDATA%/ract/keys/` on Windows) with restrictive permissions.

## Alternatives Considered

- **Inline markers** (e.g., a YAML header inside each file): fragile, invalidates the artifact content, hard to verify independently.
- **Filesystem extended attributes**: not portable across Windows and network filesystems.
- **git notes**: opaque to non-git storage and breaks when artifacts leave the repository.

## References

- `src/ract/core/rootknot.py`
- `src/ract/core/keys.py`
- `src/ract/core/provenance.py`
- `tests/property/test_rootknot_invariants.py`
