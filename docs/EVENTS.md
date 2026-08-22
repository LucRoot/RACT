---
schema_version: "6"
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

#### `sandbox.env_scrubbed`

**Added in v0.5.1 wiring module_04 (Lens C C-02 + C-10 closure).**

Emitted by every sandbox backend — `LinuxSandbox`, `MacosSandbox`, and
the Windows `UnenforcedSandbox` stub — on every `enter`. Payload
carries the environment-allowlist audit for the invocation:

- `backend` (string; one of `"linux-bwrap"`, `"macos-sandbox-exec"`,
  `"stub"`) — which backend rendered the env scrub.
- `allowlist_source` (string; one of `"manifest"`, `"file"`,
  `"default"`) — which source contributed the largest set of surviving
  names.
- `scrubbed_count` (int) — count of environment variables present on
  the harness process that were NOT allowlisted and therefore never
  reached the sandboxed child. Count-only; the substrate never logs the
  scrubbed names or values.
- `never_passthrough_denied` (int) — count of allowlist entries that
  WERE declared (in `manifest.env.passthrough` or the
  `.ract/sandbox_env.allowlist` file) but were refused by the
  `NEVER_PASSTHROUGH` deny surface. **A non-zero value on a production
  run means the manifest declared a credential-shaped name** — the
  operator should audit the manifest and remove the entry (the child
  env will not carry it either way; the counter is the audit signal).
- `credential_shaped_unblocked_count` (int) — SP Q6 amendment: count
  of allowlist entries whose SHAPE looks like a credential (suffix
  match on `_TOKEN` / `_KEY` / `_SECRET` / `_PASSWORD` / `_API` /
  `_AUTH` / etc.) but that the deny surface did NOT catch. These
  names ARE passed through (backward-compat: some legitimate build
  systems declare names like `BUILD_SIGNING_KEY_PATH`), but a
  non-zero count means the deny surface has a gap the operator
  should close by extending `NEVER_PASSTHROUGH` upstream or by
  adding the name to `.ract/never_passthrough_extra.allowlist`
  (planned v0.6). Distinct from `never_passthrough_denied`:
  denied-count means the deny surface CAUGHT the name; unblocked-
  count means the deny surface SHOULD HAVE caught the name and did
  not.

Producer sites: `src/ract/security/sandbox_linux.py::LinuxSandbox.enter`,
`src/ract/security/sandbox_macos.py::MacosSandbox.enter`,
`src/ract/security/sandbox.py::UnenforcedSandbox.enter`.

### Process group reap (v0.5.1 wiring module_05)

#### `process.reaped`

**Added in v0.5.1 wiring module_05 (Lens C C-03 closure).**

Emitted by `SubstrateLoop._reap_active_processes` once per handle SIGKILL'd.
The wire turns the process-group tree-kill from a silent WARN into a
first-class trace signal an auditor can `grep process.reaped` to reconstruct
which descendant trees each rollback path terminated.

Payload:

- `pid` (int) — the parent PID of the reaped tree (as returned by
  `subprocess.Popen.pid`). `-1` when the handle's `pid` attribute was
  unreadable (defensive; should never fire in production).
- `argv0` (string) — the command name (`argv[0]`) as spawned. NOT the whole
  argv (log-line width discipline). Empty string when the handle carries no
  argv (defensive).
- `argv_len` (int) — number of tokens in the spawn argv, so an auditor can
  correlate against known command shapes without the full argv leaking
  into the log.
- `reason` (string) — the rollback path that fired the reap. One of
  `"postcondition_failed"` (a required predicate returned `ok=False`),
  `"commit_failed"` (`WorktreeManager.commit` raised), `"run_step_exception"`
  (an uncaught exception unwound `run_step`), `"dispose_unsuccessful"`
  (`SubstrateLoop.dispose(success=False)` fired), or a caller-supplied
  string when the reaper is invoked from a test / custom path.
- `reap_latency_ms` (int) — monotonic delta from `ProcessGroupHandle.spawned_at`
  to reap in milliseconds. `0` when the spawn timestamp was unreadable.

**Audit interpretation.** A `reason="dispose_unsuccessful"` event with
`reap_latency_ms > 0` and `argv0` matching a background test process is
the fingerprint of a step_runner that spawned a long-running child and
failed to await it before the rollback. A cluster of `process.reaped`
events in a single run is not a red flag on its own — the substrate reaps
every registered handle on rollback; the operational signal is whether the
argv0 pattern points at a step_runner bug (spawn-and-forget) or a normal
rollback of a long-running test suite.

Producer site: `src/ract/executor/loop.py::_emit_process_reaped`, called
per-handle inside `SubstrateLoop._reap_active_processes`. The primitive
that actually SIGKILL'd the tree lives at
`src/ract/executor/process_group.py::kill_tree`.

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

## Memory discipline (module_09, v0.5.0)

The seven kinds below extend the closed vocabulary per master spec
§Signals items 11-13. Producers live in `src/ract/memory/events.py`
(the module_01-08 helpers) and in `src/ract/executor/loop.py`
(`retrieval.satisfied` when `SubstrateStepSpec.metadata["retrieval_
bundle"]` is populated). Payload keys reflect the retrieve / budget
/ probe surfaces landed in modules 01-08.

### `budget.declared`

Emitted when a memory-discipline function declares its per-invocation
budget. Fields: `function` (string; intake/research/plan/edit),
`declaration` (dict; `BudgetDeclaration.asdict`), `narrowing_log`
(list of `BudgetNarrowing` dicts), `source` (composition | runtime |
cli | default).

### `budget.exceeded`

Emitted by `refuse_over_ceiling` before the paired
`BudgetExceededError` raise. Fields: `function` (string),
`section_name` (string), `delta` (integer), `boundary` (`input_max`
or `hard_ceiling`).

### `retrieval.requested`

Emitted by `retrieve()` at cascade entry. Fields:
`canonical_query` (dict; `canonical_query_payload` output),
`budget` (integer; retrieve-local sub-budget), `call_id` (hex).

### `retrieval.satisfied`

Emitted by `retrieve()` on a returned bundle AND by
`SubstrateLoop.run_step` when the step's spec carries a bundle in
`metadata["retrieval_bundle"]`. Fields: `call_id` (hex string),
`total_tokens` (integer), `budget_used_pct` (float), and `step_id`
(hex) on the loop-side emission.

### `retrieval.cascaded`

Emitted when the four-level retrieve cascade downgrades a level.
Fields: `call_id` (hex), `from_level` (integer 1-4), `to_level`
(integer 1-4), `reason` (string).

### `retrieval.refused`

Emitted when the retrieve cascade exhausts every level and returns
an empty bundle. Fields: `call_id` (hex), `reason` (string).

### `probe.evaluated`

Emitted by the self-adjustment probe scheduler on each probe
completion. Fields: `probe` (needle | coherence | adherence),
`score` (float 0.0-1.0), `repo_fingerprint` (hex), `note` (string).

## v0.5.1 External Review Response (schema_version 4)

The seven kinds below extend the closed vocabulary under
schema_version 4. Producers:

- `assumption.accepted` — `ract.core.assumptions.AssumptionRegistry.accept`
  (module_01 -- WAL crash-consistency layer).
- `tool.invocation.pre|post|refused` —
  `ract.executor.tool_gate.ToolInvocationGate._emit` /
  `_refuse` (module_05 -- SubstrateLoop shim closure). The three
  strings are emitted directly by the gate; the
  `src/ract/trace/events.py::EventKind` Literal folds them into
  the closed vocabulary at the write-time gate.
- `manifest.ledger.appended|refused` —
  `ract.security.manifest_ledger.ManifestLedger.append` /
  observer refusal path (module_07 -- Historical Manifest
  Ledger).
- `whisperer.contract_violation` —
  `ract.antilazy.sycophancy_v2.SycophancyClassification.emit_event`
  (module_09 -- Sycophancy classifier upgrade).

### `assumption.accepted`

Emitted by `AssumptionRegistry.accept` when a proposed assumption
is durably persisted to the WAL at `.ract/assumptions.wal`. Fields:
`run_id` (string, hex; ambient or empty), `assumption_id` (string,
hex UUID), `evidence_digest` (string; SHA-256 of the evidence bytes
that justified acceptance, canonicalised via
`ract.canonical.dumps_jcs`).

Example payload:

```json
{
  "run_id": "4a1c0f9e6b3d2a5c8f9e1b4d2a7c6f3e",
  "assumption_id": "d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6",
  "evidence_digest": "sha256:9f8e7d6c5b4a39281706f5e4d3c2b1a0…"
}
```

> **Wiring gap (v0.5.1 module_03 scope).** The three
> `tool.invocation.pre|post|refused` kinds below are emitted
> directly by `src/ract/executor/tool_gate.py` as raw string
> literals; they are documented here as part of the v0.5.1
> vocabulary but are NOT YET in the closed `EventKind` Literal
> at `src/ract/trace/events.py` (which today carries the older
> `tool.called` / `tool.result` / `tool.refused` shape). The
> wiring completion pipeline's module_03 (tool gate chokepoint
> wiring) extends the Literal + wires every production tool
> caller through `SubstrateLoop.invoke_tool`. Consumers can
> treat the payload shapes below as stable; the type-enforcement
> gate lands with module_03.

### `tool.invocation.pre`

Emitted by `ToolInvocationGate.invoke` before the tool callable
runs, after all four gates (manifest / registry / args / budget)
have accepted. Fields: `run_id` (string, hex; ambient), `tool_id`
(string), `args_repr` (string; bounded / privacy-safe repr of the
call arguments), `budget_used` (int; invocations already consumed
this step), `budget_max` (int; per-step ceiling from
`InvocationBudget.max_invocations`).

### `tool.invocation.post`

Emitted by `ToolInvocationGate.invoke` after the tool callable
returns (success) or raises (failure). Fields: `run_id` (string,
hex), `tool_id` (string), `ok` (bool), `latency_ms` (float);
on success: `result_size_bytes` (int; approximate serialised
size of the return value); on failure: `exception` (string;
`type(exc).__name__` of the raised exception).

### `tool.invocation.refused`

Emitted by `ToolInvocationGate._refuse` when any of the four
gates rejects a call. Fields: `run_id` (string, hex), `tool_id`
(string), `gate` (string; one of `manifest` / `registry` /
`args` / `budget`), `reason` (string; short human-readable
diagnostic), `details` (dict; gate-specific structured payload
carrying e.g. the missing schema field name for `args`, the
ceiling / used counts for `budget`, or the declared-set diff for
`manifest` / `registry`).

### `manifest.ledger.appended`

Emitted by `ManifestLedger.append` on every successful entry
write. Fields: `entry_index` (int; the 0-based ledger position
of the appended entry), `manifest_digest` (string; hex of the
observed manifest's canonical digest), `prev_ledger_hash`
(string; hex of the previous entry's chain hash, or GENESIS
sentinel for the first entry), `tool_ids_invoked_count` (int;
number of distinct tool ids invoked in the substrate step at
ledger-append time).

### `manifest.ledger.refused`

Emitted by the ledger observer when a ledger IS bound (an ambient
ledger accessor returns a live instance) but the append fails
(disk full, permission change, lock contention, malformed
payload). Fields: `entry_index` (int; the attempted position;
`-1` when the position could not be resolved), `reason` (string;
one of `lock_contended` / `disk_full` / `permission_denied` /
`malformed_payload` / `chain_mismatch`), `details` (dict;
free-form structured diagnostic carrying `exception_name`
+ `exception_message` fields plus a `manifest_digest_hex` when
the ledger reached the entry-shape validation step).
`ract verify` uses this event to distinguish "ledger was never
bound" (no event) from "ledger was bound but refused" (this
event) -- the two failure modes get different exit codes.

### `whisperer.contract_violation`

Emitted by
`ract.antilazy.sycophancy_v2.SycophancyClassification.emit_event`
whenever `is_sycophantic` is True (SP Q4a lifted the emit gate
to the composed verdict, not the commitment-floor branch alone).
Fields: `run_id` (string, hex; ambient or empty), `commitment_count`
(int; sum of AST commitments + factual claims), `floor` (int;
`MIN_COMMITMENT_FLOOR` at classify time, default 3),
`response_excerpt_hash` (string; 16-hex prefix of SHA-256 over
the first 256 bytes of the response),
`response_full_hash` (string; 64-hex SHA-256 over the entire
response body -- SP Q4b amendment, disambiguates long-prefix
collisions), `null_op_score` (float 0.0-1.0),
`null_op_threshold` (float; the `NULL_OP_SCORE_THRESHOLD` in
effect at classify time, default 0.7 -- SP Q3 exposes runtime
overrides that land on this payload), `trigger` (string; one of
`null_op` / `commitment_floor` / `both` -- SP Q4a; names which
signal fired), `used_regex_fallback` (bool; True when
grammar-parse failed and the classifier degraded to the
regex-only fallback path).

See `docs/ADRs/ADR-0042-sycophancy-v2-tuning-band.md` for the
tuning-band provenance behind the `floor` and `null_op_threshold`
defaults.

<!-- schema_version: 4 — v0.5.1 External Review Response (added assumption.accepted, tool.invocation.pre|post|refused, manifest.ledger.appended|refused, whisperer.contract_violation) -->

## v0.5.1 spec-completeness module_02 (schema_version 6)

The kind below extends the closed vocabulary under schema_version 6.
Producer:

- `state.budget_capped` — `ract.memory.functions.provider_adapter.seat_state_section`
  (module_02 -- 15%-of-input_target sub-budget cap on the state
  section, closes Lens 1A CRITICAL A-2).

### `state.budget_capped`

Emitted by
`ract.memory.functions.provider_adapter.seat_state_section` when the
proposed `state_context` section's token cost exceeds
`floor(0.15 * declaration.input_target)` -- the master spec's
sub-budget cap
(`docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md` §Context Composition
line 71: "state_context bounded at 15% of input budget"). The
truncation strategy is `truncate_tail`: the helper drops trailing
lines one at a time and appends a one-line
`[TRUNCATED: state_context capped at N tokens; K lines dropped from
tail]` marker; the marker counts toward the seated size so the seated
total is `<= cap_tokens`. Future strategies may report entry drops or
summarization; the `strategy` field names which one fired.

Fields:

- `function` (string; `intake` / `research` / `plan` / `edit`).
- `cap_tokens` (int; `floor(0.15 * input_target)`).
- `requested_tokens` (int; pre-truncate seated size).
- `seated_tokens` (int; post-truncate seated size — always `<=
  cap_tokens`).
- `dropped_entry_count` (int; lines dropped by the truncation walk
  under strategy `truncate_tail`).
- `strategy` (string; currently only `truncate_tail`).
- `requested_hash` (string; SHA-256 hex of the pre-truncate content
  so the audit trail can reconstruct what was requested vs seated).

Example payload:

```json
{
  "function": "plan",
  "cap_tokens": 600,
  "requested_tokens": 872,
  "seated_tokens": 599,
  "dropped_entry_count": 14,
  "strategy": "truncate_tail",
  "requested_hash": "3f5e…"
}
```

<!-- schema_version: 6 — v0.5.1 spec-completeness module_02 (added state.budget_capped) -->

## v0.5.1 spec-completeness module_03 -- repair-synthesized close events (schema_version 6, no new kind)

Module_03 (Lens 2 Delta 1) adds :mod:`ract.trace.repair`, which
synthesizes close events for open handles in a possibly-truncated
event log. Repair uses the EXISTING closed EventKind vocabulary
(no new kind, no schema bump). Synthesized close events carry
three payload-shape additions on top of the base close event's
schema:

- `synthesized` (boolean; always `true` when present) -- flag
  distinguishing a synthesized close from a real one.
- `reason` (string; `"interrupted"` today; future values may name
  a different repair cause).
- `source_event_id` (string; hex of the open event's id). The
  by-id pairing rule that makes ``repair(repair(x)) == repair(x))``
  idempotent.

Additional per-close-kind fields:

- `run.aborted` (synth): base payload keys only.
- `step.rolled_back` (synth): base payload keys only.
- `tool.result` (synth): adds `status: "unknown"` — signals to
  downstream consumers that the tool's outcome cannot be
  reconstructed from the log.
- `response.received` (synth): adds `status: "timed_out"` — signals
  that the LLM request never received a response before the log
  was truncated.
- `handshake.resolved` (synth): adds `resolution: "interrupted"`.

Example synthesized `run.aborted`:

```json
{
  "kind": "run.aborted",
  "payload": {
    "synthesized": true,
    "reason": "interrupted",
    "source_event_id": "3fa85f6417174562b3fc2c963f66afa6"
  }
}
```

Consumers filtering for real closes MUST check
``payload.get("synthesized")`` -- a synth close is a repair
projection, not an authoritative run terminator. See
:func:`ract.trace.repair.repair` docstring for the full open->close
map and determinism contract.

Fiber-lifecycle event kinds (``fiber.activated`` / ``fiber.disposed``
/ ``fiber.failed``) are NOT part of the closed vocabulary in v0.5.1
per the audit's Delta 1 recommendation (§5.2 loops-as-fibers not
adopted); their addition would be a schema_version bump.

