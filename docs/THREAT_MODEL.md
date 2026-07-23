# RACT Threat Model

This document describes how RACT classifies and controls tool execution.

## Capability tiers

Every plan action and MCP tool call is classified into one of four tiers.

| Tier | Name | Examples | Default policy |
|------|------|----------|----------------|
| T0 | Read-only | file read, symbol search, `git log` | Allow |
| T1 | Workspace-write | file write inside the workspace root | Allow with Rootknot |
| T2 | Environment | `pip install`, `npm install`, `git commit`, network fetch | Require operator handshake |
| T3 | External | shell outside the workspace, package publish, `rm -rf` on untracked paths | Refuse by default |

The classification is deterministic: it comes from the step's schema fields (`action`, `expected_artifact`, `tool_call.name`), not from parsing free text.

## Sandbox

- **T1** writes are restricted to paths under the configured workspace root. Absolute paths and paths that resolve outside the workspace are refused.
- **T2** actions require an operator handshake before execution. Network calls are scoped to a per-plan allowlist when one is configured.
- **T3** actions are refused unless the session was started with `--allow-tier-3`, and even then each action must be handshake-approved.

## Refuse-list

RACT refuses the following actions with a structured log entry and a refusal record in the run report:

1. Writing or modifying files outside the workspace root.
2. Executing `rm -rf` / `rm -r` / `rmdir /s` on paths not under version control.
3. Publishing to package registries (PyPI, npm, crates.io, etc.) without `--allow-tier-3` and an operator-signed handshake.
4. Committing directly to a protected branch.
5. Sending the full workspace to a remote provider in a single request above the configured chunk size threshold (default 1 MiB).
6. Reading files matching the sensitive-pattern list: `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`, `~/.ssh/**`, `~/.aws/**`, `~/.config/gcloud/**`.
7. Overwriting a file whose current Rootknot was signed by a different session key, unless the operator explicitly passes `--force-overwrite <path>`.

## Reporting

See [SECURITY.md](../SECURITY.md) for the vulnerability reporting policy and PGP key.
