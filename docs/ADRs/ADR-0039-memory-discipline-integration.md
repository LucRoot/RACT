# ADR-0039: Memory-discipline integration with SubstrateLoop, Rootknot, and ALM

Status: accepted (v0.5.0 Memory Discipline, module_09).

## Context

Modules 01-08 shipped the memory-discipline substrate as parallel
surfaces: the token-budget accountant, three indexes (symbol / graph
/ semantic), a retrieve primitive with a four-level cascade, four
function contracts (intake / research / plan / edit), four playbooks
with a composition runner, and self-adjustment probes with a failure
aggregator.

Module_09 wires these surfaces into the existing v0.4.1 core so a
running RACT session actually consumes them. The load-bearing
questions:

- How does a retrieval bundle produced by the retrieve primitive
  reach the model call inside `SubstrateLoop.run_step` without
  changing the loop's v0.4.x callers?
- How does the seven-item bump to the closed `EventKind` vocabulary
  land without breaking the golden-hash gate or the JsonlEventWriter
  round-trip?
- How does `Rootknot` carry a retrieval attestation without breaking
  the compatibility reader path for v1, v2, or v3-without-attestation
  sidecars? (Sacred spine invariant.)
- How do ALM gates G6 (under-edit closure) and G7 (companion review)
  extend to consume module_06's `CandidateDiff` without breaking the
  v0.3/v0.4 legacy paths that predate the four function contracts?
- What CLI surface does an operator get for the three new
  operational verbs (`memory init`, `memory apply-narrowings`,
  `retrieval query`)?

## Decision

**SubstrateStepSpec.metadata is the wiring channel.** The v0.4.x
`SubstrateStepSpec` gains a free-form `metadata: dict` field
(defaulting to `{}`). `SubstrateLoop.run_step` reads
`metadata["retrieval_bundle"]` when present and emits a
`retrieval.satisfied` event with the bundle's `total_tokens`,
`budget_used_pct`, and `call_id`. When the key is absent the loop
proceeds exactly as today — deterministic non-model steps and every
v0.4.x caller see no behavior change.

**EventKind bumps by seven closed-vocabulary members.** Master spec
§Signals items 11-13 name the additions: `budget.declared`,
`budget.exceeded`, `retrieval.requested`, `retrieval.satisfied`,
`retrieval.cascaded`, `retrieval.refused`, `probe.evaluated`.
`LEGAL_EVENT_KINDS` auto-recomputes from the `Literal` alias via
`typing.get_args`, so the frozenset stays in sync with the type.
`ract.memory.events.MEMORY_EVENT_KINDS` mirrors these as strings for
the module_01-08 helpers already shipped. Module_10 re-locks the
golden hash to accept the vocabulary expansion.

**Rootknot gains an optional `retrieval_attestation: Digest | None`
field.** The field is INCLUDED in `canonical_bytes()` ONLY when it is
non-None; older v1/v2/v3 sidecars without the field produce the same
canonical bytes as before the module lands and continue to verify
under the compatibility reader. `make_rootknot_v3` gains a matching
kwarg. `bundle_digest(bytes) -> Digest` is a small SHA-256 helper the
retrieve wiring calls to build the attestation value; kept in
`ract.core.rootknot` so the sacred spine does not import
`ract.memory.retrieve`. Sacred-spine test
`test_older_sidecar_still_verifies` pins the compatibility path.

**Two new ALM gate helpers wrap the edit-path.** `enforce_g6_edit
(diff, plan)` refuses when the diff touches a file not named in
`plan.load_manifest`. `enforce_g7_edit(diff, companion)` calls
`companion.review(diff)` and refuses on the (False, reason) verdict.
Both raise `LazinessViolatedError(kind=...)` and emit
`laziness.violated` to the trace. The legacy `enforce_g6(transaction,
graph, edited_symbols)` above is UNCHANGED so v0.3/v0.4 callers keep
working; the new helpers are the shape module_06's edit function
calls at commit time. `CompanionProvider` is a Protocol with a
single `review` method — bridges to real providers live outside
`pre_commit.py`.

**Three new CLI verbs.** `ract memory init <path>` runs the initial
build over the symbol, graph, and semantic indexes for a repo
(`--skip-semantic` opts out when LanceDB or the embedding model is
unavailable). `ract memory apply-narrowings [--dry-run]` invokes the
failure-record aggregator and writes proposed narrowings to
`.ract/memory/budget_overrides.yaml`. `ract retrieval query <query>`
extends the existing `ract retrieval` verb with a `query` subverb;
the legacy `search` shape is unchanged. `CLI_VERBS` gains `memory`.

## Rejected alternatives

**Parallel-loop-for-memory.** A second loop that drives memory-
discipline surfaces alongside `SubstrateLoop`. Rejected: two loops
competing over the same worktree contend at commit time and each
would need its own event-chain writer, doubling the number of hash
chains an operator has to reconcile at end-of-run. Threading the
bundle onto the existing loop's per-step metadata avoids the
duplication.

**Replace-SubstrateLoop-entirely.** A v0.5-native loop that reads
retrieval bundles as a first-class field on `SubstrateStepSpec` and
drops the `metadata: dict` catch-all. Rejected: breaks every v0.4.x
caller (`substrate_adapter.py`, `contracts.test_auction_wired_into_
substrate_loop.py`, the harness shim) and forces a large-surface
migration inside one module. The `metadata: dict` extension is
opt-in per caller.

**Memory-discipline-outside-the-loop.** Have module_06's edit
function attach the retrieval bundle to the artifact directly, with
`Rootknot.retrieval_attestation` populated from the artifact's
sidecar path rather than from the loop. Rejected: breaks the
Rootknot attestation chain — the loop is the only surface that knows
which bundle actually reached the model call for a given step, and
routing the attestation outside the loop opens a gap where two
sibling model calls could share one attestation.

## Consequences

**Sacred spine preserved.** Rootknot's 3-signature schema stays
intact. Older sidecars verify unchanged. The closed-IP wordlist
gate returns zero hits at the module tip. The author-name-free
tree is untouched. ALM AL-1 continues to sign over v3-canonical
bytes; a knot with `retrieval_attestation` set produces canonical
bytes that INCLUDE the field, so the anti-lazy signature attests
the exact retrieval that reached the model.

**Golden hash bumps** because the seven `EventKind` additions
change `src/ract/trace/events.py`'s source bytes. Module_10 re-locks
the golden hash to accept the vocabulary expansion; the loop
constructor and existing writers require no changes because
`LEGAL_EVENT_KINDS` auto-recomputes.

**Legacy paths preserved.** `enforce_g6` (workspace snapshot +
symbol graph) still exists for v0.3/v0.4 callers. Module_06's edit
function calls `enforce_g6_edit` + `enforce_g7_edit` at commit
time; the existing `SubstrateLoop._finalize` path (worktree commit)
is unchanged. `SubstrateStepSpec.metadata` defaults to `{}` so a
caller who constructs a spec without the field sees no behavior
change.

**Flagged gaps for v0.6.** The full three-index wiring of `ract
retrieval query` against a live retrieve pipeline reaches only a
canonical projection today; a wider integration lands with a fresh
prompt-coverage sweep. The provider-bridge for
`MemoryFunctionProvider` → `ProviderAdapter.complete` is a small
adapter (log entry in the failure aggregator surface, not called
out in DoD); the `SUMMARY` provider adapter lands as part of the
same v0.6 pass. Multiple constraints inbound from module_04-08
POSTs (probe_lancedb at startup, verify_prompt_coverage at
startup, fingerprint mapper at retrieve setup, current_budgets
from probes, PhaseRecord token counts, tmp-file cleanup on
SIGKILL, watcher-glob exclusion for probe fixtures) are logged
under module_09 `## Flagged gaps` for the v0.6 hardening pass —
they do not gate the DoD but they are the operational polish
items that turn the surface from "landed" to "production-ready".

## References

- Master spec: `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`
  §Integration surface, §Sacred spine invariants, §Signals.
- Module fragment: `_BUILD/ract_v0.5.0_memory_discipline/module_09.md`.
- Sacred-spine test:
  `tests/memory/test_rootknot_retrieval_attestation.py::test_older_sidecar_still_verifies`.
