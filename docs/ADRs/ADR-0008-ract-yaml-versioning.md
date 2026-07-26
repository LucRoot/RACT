# ADR-0008: `ract.yaml` Schema Versioning

## Status

Accepted

## Context

`ract.yaml` configures the manager provider, provider endpoints, prompts
directory, and coverage gate for a RACT workspace. As RACT evolves, the set of
recognized keys and their semantics will change. Without a version field, a
workspace created against an older RACT would either fail opaquely at runtime
(unknown key ignored, required key missing) or be silently reinterpreted by a
newer RACT that attaches different meaning to an existing key. Both are
silent-failure modes that the architecture refuses to tolerate (see
`docs/ARCHITECTURE.md`, "Failure modes and concurrency").

The plan schema already carries a `schema_version` and rejects unknown versions
(`src/ract/plan_validator.py`). The configuration file needs the same discipline.

## Decision

`ract.yaml` carries a top-level `schema_version` string. On load:

- If `schema_version` is absent, RACT rejects the file with a clear error
  naming the missing field. It does not guess a default.
- If `schema_version` is present but unknown to the running RACT, RACT rejects
  the file and points the operator at the migration path.
- Migrations between versions are explicit scripts under `scripts/migrations/`,
  each named `ract_yaml_<from>_to_<to>.py`. RACT never silently upgrades a
  workspace's configuration in place. The operator runs the migration; RACT
  verifies the result.

The current schema version is recorded alongside the version constant in
`src/ract/config.py` so the accepted-version list is discoverable from code.

## Consequences

- A configuration file is self-describing: a reader can tell which RACT version
  it targets without running the tool.
- Breaking config changes require a migration script and a version bump, which
  makes the cost of a breaking change visible at review time.
- Old workspaces stop loading against a new RACT until migrated — by design.
  The error message names the migration to run.

## Alternatives Considered

- **Silent upgrades (rewrite the file on load).** Rejected. Mutating an
  operator's configuration file without an explicit action violates the
  workspace-write contract and the threat-model Tier-2 handshake rule.
- **JSON Schema only, no version field.** Rejected. A schema validates shape,
  not intent. Two RACT versions can both accept the same shape while attaching
  different semantics to a key, which is exactly the silent reinterpretation
  this ADR exists to prevent.
- **No versioning; document the current keys.** Rejected. Documentation is not
  enforceable; a missing version field cannot be detected at load time.

## References

- `ract.yaml`
- `src/ract/config.py`
- `src/ract/plan_validator.py` (the existing `schema_version` precedent)
- `scripts/migrations/` (location for future migration scripts)
