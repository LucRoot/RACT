# ADR-0007: What RACT Refuses

## Status

Accepted

## Context

A threat model is only as strong as its boundary. Users and reviewers need a concrete list of actions RACT will not perform, not a vague statement that the system is "safe." This ADR publishes that boundary and binds the implementation to it.

## Decision

RACT maintains a refuse-list enforced by `authorize_action` in `src/ract/core/threat_model.py`. The following actions are always refused, with a structured `Refusal` record in the run report:

1. **Workspace escape.** Writing or modifying files that resolve outside the configured workspace root.
2. **Untracked destructive deletion.** Executing `rm -rf`, `rm -r`, or `rmdir /s` on paths not under version control.
3. **Package-registry publish.** Publishing to PyPI, npm, crates.io, or similar without `--allow-tier-3` and an operator-signed handshake.
4. **Protected-branch commit.** Committing directly to a branch marked protected by local git configuration.
5. **Bulk workspace exfiltration.** Sending the full workspace to a remote provider in a single request above the chunk threshold (default 1 MiB).
6. **Sensitive-file read.** Reading paths matching `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`, `~/.ssh/**`, `~/.aws/**`, or `~/.config/gcloud/**`.
7. **Cross-session overwrite.** Overwriting a file whose current Rootknot was signed by a different session key, unless the operator passes `--force-overwrite <path>`.

Each refusal names the action, the reason, the tier, and relevant details (path, threshold, etc.). The executor checks every step against this list before dispatch.

## Consequences

- The boundary is public, testable, and versioned alongside the code.
- Users can predict which operations will require `--allow-tier-3` or a handshake.
- Security reviewers can audit the refusal paths directly in `tests/security/`.

## References

- `src/ract/core/threat_model.py`
- `docs/THREAT_MODEL.md`
- `tests/security/test_refuse_list.py`
