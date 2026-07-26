---
schema_version: "2"
---

# RACT event schema

**Origin.** SUBSTRATE spec §6 (Substrate Layer 5: The Trace is the
Product) and §11 signals 9, 10, 11. Every load-bearing decision a run
makes lands as one event in the hash-chained JSONL log at
`evals/runs/<run_id>/events.jsonl`. The log is the source of truth;
`RunReporter` is a projection over it (module_05 migration).

The vocabulary is **closed**. Adding a new event kind requires:

1. Adding the string literal to `EventKind` in
   `src/ract/trace/events.py`.
2. Adding the kind's payload schema and one canonical example to this
   document.
3. Bumping the `schema_version` in this document's frontmatter.
4. Naming the emit site in the module that introduced it.

Reference sources:

- SUBSTRATE §6, §11.
- OpenTelemetry GenAI Semantic Conventions SIG:
  `https://github.com/open-telemetry/semantic-conventions` — the kinds
  mirror the conventions' multi-agent vocabulary (tasks, actions,
  memory, agent teams, artifact tracking).
- Temporal durable-execution model:
  `https://docs.temporal.io/` — the workflow-history-as-source-of-truth
  pattern that motivates the projection-based reporter.
- JSON Schema Draft 2020-12: `https://json-schema.org/` — canonical
  payload form.
- ADR-0015 — the OpenTelemetry runtime dep + this schema.

## Common event envelope

Every event carries the following fields regardless of kind:

- `id` — 16-byte UUID, hex-encoded.
- `run_id` — 16-byte UUID identifying the run.
- `step_id` — 16-byte UUID or `null`; set for step-scoped events.
- `parent_id` — 16-byte UUID or `null`; set for causality chains.
- `timestamp_ns` — integer nanoseconds since the Unix epoch.
- `kind` — one of the closed `EventKind` literals below.
- `payload` — kind-specific structured dict (schemas below).
- `hash` — SHA-256 of the canonical serialisation of every field
  above plus `prev_hash` (32 bytes, hex-encoded).
- `prev_hash` — SHA-256 of the previous event's `hash` (32 bytes,
  hex-encoded). The chain's genesis is 32 zero bytes.

`EventReader.load(path)` reads the log line-by-line and re-hashes each
event; a mismatched `prev_hash` or a re-hash disagreement raises
`ChainBrokenError` at load time.

## Determinism contract for `ract trace replay`

Replay requires that the tool layer be deterministic given the same
inputs. The event log records the model's `response.received` payloads,
so the model layer is trivially replayable; the tool layer's
determinism depends on the sandbox (module_03) and worktree (module_02)
already being deterministic given the same inputs. `ract trace replay`
emits a warning when the workspace's HEAD does not match the run's
initial snapshot; a mismatch means the replay may diverge on the first
worktree-shaped operation.

## Closed EventKind vocabulary

Every kind's payload is a JSON dict; keys with no value are omitted.

### Run lifecycle

#### `run.started`

Emitted by `IntentCompiler.compile` after the frozen `AcceptanceSuite`
is built.

Fields:

- `intent_id` (string, hex UUID) — the suite's intent id.
- `suite_digest` (string) — deterministic digest of the compiled suite.
- `compiler_version` (string).
- `predicate_count` (int).
- `required_count` (int).
- `coverage_gate` (float).

Example payload:

```json
{
  "intent_id": "d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6",
  "suite_digest": "sha256:…",
  "compiler_version": "0.4.0",
  "predicate_count": 4,
  "required_count": 4,
  "coverage_gate": 0.85
}
```

#### `run.completed`

Emitted at run close when the acceptance gate is satisfied.

Fields: `final_decision` (string), `duration_ns` (int), `event_count`
(int).

#### `run.aborted`

Emitted at run close when the loop halts before the gate is satisfied.

Fields: `termination_cause` (string; one of `TerminationCause` names),
`reason` (string), `duration_ns` (int).

### Step transactions (module_02)

#### `step.started`

Emitted by `open_transaction` in `ract.core.transaction`.

Fields:

- `parent_snapshot` (string, git sha).
- `branch` (string, `rootact/step/<step_id_hex>`).
- `postcondition_count` (int).
- `manifest_digest` (string or null).
- `timeout_seconds` (int).

#### `step.committed`

Emitted by `SubstrateLoop._finalize` when the worktree commit lands.

Fields: `outcome` (`"COMMITTED"`), `parent_snapshot_before` (string),
`parent_snapshot_after` (string), `branch` (string), `reason` (string).

#### `step.rolled_back`

Emitted for `ROLLED_BACK` and `BLOCKED_ON_HANDSHAKE` outcomes.

Fields: same as `step.committed`, with `reason` naming the block or
failure.

### Provider I/O (module_04)

#### `prompt.sent`

Emitted by `send_with_trace` in `ract.providers.provider` before the
provider call.

Fields: `provider` (string), `response_shape` (string), `intent_id`
(string), `prompt_chars` (int).

#### `response.received`

Emitted after the provider call returns; carries a preview of the
response type and up to 200 characters of the payload.

Fields: `provider` (string), `intent_id` (string), `response_type`
(string), `preview` (string).

#### `response.validated`

Emitted by `ResponseValidator.parse` on success.

Fields: `step_id` (string), `kind` (string; one of the closed
`ActionKind` literals).

#### `response.rejected`

Emitted by `ResponseValidator.parse` on failure.

Fields: `step_id` (string), `error` (string), `attempt` (int),
`should_halt` (bool).

### Tool dispatch

#### `tool.called`

Emitted at the tool dispatch site (invocation of a `PlannedStep`'s
action against the workspace).

Fields: `tool` (string), `arguments` (dict, redacted per profile).

#### `tool.result`

Emitted when a tool call returns.

Fields: `tool` (string), `ok` (bool), `duration_ns` (int).

#### `tool.refused`

Emitted when a tool call is refused (sandbox, policy, handshake, or
manifest).

Fields: `tool` (string), `reason` (string), `refused_by` (string;
`"sandbox"` / `"policy"` / `"handshake"` / `"manifest"`).

### Sandbox (module_03)

#### `sandbox.granted`

Emitted by `LinuxSandbox` / `MacosSandbox` on successful `enter`.

Fields: `manifest_digest` (string), `reason` (string), `details` (dict).

#### `sandbox.denied`

Emitted when `enter` refuses the manifest.

Fields: `manifest_digest` (string), `reason` (string), `details` (dict).

#### `sandbox.unenforced`

Emitted by `UnenforcedSandbox` on each `enter` — loud in the log by
design (see ADR-0012).

Fields: `manifest_digest` (string), `reason` (string), `details` (dict).

### Predicates (module_01)

#### `predicate.evaluated`

Emitted by `AcceptancePredicate.evaluate` after every evaluation.

Fields: `predicate_id` (string), `kind` (string; one of `test` / `type`
/ `property` / `invariant` / `artifact`), `required` (bool), `ok`
(bool), `reason` (string), `duration_ns` (int).

### Handshakes

#### `handshake.requested`

Emitted by `HandshakeRegistry.add`.

Fields: `milestone_id` (string), `status` (string; always `"pending"`
at request time), `description` (string), `reason` (string).

#### `handshake.resolved`

Emitted by `HandshakeRegistry.update_status`.

Fields: same shape; `status` is one of `approved` / `rejected` /
`deferred`.

### Rootknot / provenance (module_06 extends)

#### `rootknot.created`

Emitted by `ProvenanceIndex.save`.

Fields: `workspace_path` (string), `plan_id` (string, hex UUID),
`step_id_ref` (string, hex UUID), `artifact_digest` (string),
`assumption_digest` (string).

#### `rootknot.verified`

Emitted by `verify_workspace` per-verified knot.

Fields: `workspace_path` (string), `artifact_digest` (string).

### Assumptions

#### `assumption.proposed`

Emitted by `AssumptionRegistry.propose`.

Fields: `assumption_id` (string, hex UUID), `digest` (string), `text`
(string).

#### `assumption.discharged`

Emitted by `AssumptionRegistry.discharge`.

Fields: `assumption_id` (string, hex UUID), `digest` (string).

#### `assumption.violated`

Emitted by `AssumptionRegistry.violate` for the primary and every
propagated dependent.

Fields: `assumption_id` (string, hex UUID), `root_id` (string; the
originating assumption id).

### Contracts (module_06)

#### `auction.proposal`

Emitted by `AuctionSweep.run` — one event per staged
`DeletionProposal`. The Auction is a scheduled between-iteration
sweep (SUBSTRATE §8); nothing is deleted without operator sign-off.

Fields: `workspace_path` (string; workspace-relative path of the
proposed deletion), `last_modified_days` (integer; file age at scan
time), `inbound_references` (integer; count of graph edges into the
target from other modules), `reason` (string; short human-readable
justification).

## Redaction profile

The optional `RedactionProfile` in `ract.trace.writer` scrubs listed
regex patterns and fully-redacts named payload fields before write. It
is off by default; enable it in `ract.yaml`:

```yaml
trace:
  redaction:
    patterns:
      - "sk-[A-Za-z0-9]{20,}"
    fields:
      - api_key
    replacement: "[REDACTED]"
```

The profile is intentionally shallow — a first line of defence for
shared logs, not a data-loss-prevention layer. Deeper redaction is v0.5
hardening (per ADR-0015).

<!-- schema_version: 2 — module_06 v0.4.0 (added auction.proposal) -->
