# ADR-0038: Probe-derived budgets narrow spec defaults

Status: accepted (v0.5.0 Memory Discipline, module_08).

## Context

Module_01 shipped a token budget system with per-function defaults
loaded from `src/ract/memory/budget_defaults.yaml`. Those defaults are
spec-time choices: they encode what a "typical" provider tolerates on
a "typical" repo, and they were pinned before any measurement fired
against the actual provider mix an operator runs.

The master spec §Self-adjustment names the problem: budgets should
derive from measured behavior on the actual provider, not from static
defaults that silently drift as providers evolve. §Signals item 10
tags the probe surface as a v0.5.0 signal: three probes must exist
under `src/ract/memory/probes/`, and the first probe run must write
`.rack/probes/capability.json`.

The load-bearing questions:

- What is the minimum probe suite that distinguishes "the provider
  works well at this size" from "the provider degrades at this size"?
- How does a probe-derived narrowing propagate to the budget layer
  without introducing a second widening path (module_01's runtime-
  narrowing helper already refuses widenings)?
- How does the failure-record aggregator produce narrowing proposals
  that respect the always-narrowing invariant even under adversarial
  input (e.g. a run where every failure records `input_token_count`
  larger than the current declaration)?
- How does the repo fingerprint feed per-repo retrieval defaults
  without hidden state that would make the mapping drift run-to-run?

## Alternatives considered

**1. Static spec-time budgets forever.** Rejected. The spec defaults
are pinned against a provider snapshot from spec-drafting time; the
provider mix in production drifts every quarter. A static default is
correct at the moment it lands and wrong every quarter thereafter.
The signals in §Overflow handling (`retrieval.cascaded`,
`retrieval.refused`) can locate the drift, but only if something
consumes them. Probes are that something.

**2. Full model-side self-tuning (probe-derived defaults feed a
learned per-repo LoRA head).** Rejected. Opaque: a caller cannot
attribute a specific narrowing to a specific measurement, so a
regression debug session has no anchor. The master spec §Trust
direction requires explicit attribution; a learned head fails that
requirement.

**3. Operator-only manual tuning.** Rejected. Master spec §Signals
item 10 names the automated probe surface as a v0.5.0 signal. Manual
tuning leaves the measurement machinery unbuilt; every operator
re-derives the same knobs by hand.

**4. Three probes (needle / coherence / adherence) + failure-record
aggregator + per-repo fingerprint (accepted).** Ships in v0.5.0
per master spec §Bounded scope. Nightly recompilation and the drift
detector defer to v0.6 because they are automation surfaces on top
of the probes rather than probes themselves.

## Decision

**Probes.** Land three probe suites under `src/ract/memory/probes/`:

- `needle.py` — insert a specific fact at depths (5% / 25% / 50% /
  75% / 95%) in contexts of size (2k / 4k / 8k / 16k) tokens; ask a
  question requiring the fact; record recall. Report:
  `recall_at_depth: dict[float, dict[int, bool]]`,
  `usable_context_window: int`. The window is the largest size at
  which every depth still recalled — a single miss at any depth
  pins the window to the previous size, so one bad response at
  depth=0.95 does not inflate a false floor upward.
- `coherence.py` — provide long context with a subtle inconsistency
  (two contradictory statements about the same fact); ask the model
  to identify it; require both contradictory tokens in the response
  for a "hit". Report: `identified_at_size: dict[int, bool]`,
  `reasoning_quality_bound: int`.
- `adherence.py` — provide long context with a specific instruction
  seated at the beginning (prefix every answer with `CROW:`); ask
  a question at the end; require the prefix (case-sensitive) for a
  "hit". Report: `instruction_persistence_at_size: dict[int, bool]`,
  `persistence_bound: int`.

**Scheduler.** Land `src/ract/memory/probes/scheduler.py`:

- `ProbeScheduler.run_once(provider)` invokes the three probes with
  the same provider and sink.
- `write_capability_record(reports, root)` reduces the three reports
  into a `ModelCapability` record and writes it atomically to
  `.rack/probes/capability.json`. Atomic-replace via tmp + fsync +
  `os.replace` closes the Second Pass Q4 corruption risk.
- `read_capability_record(root)` returns the record or `None` on
  missing file. Malformed JSON raises `ValueError`; unsupported
  schema version raises `ValueError`. Silent revert-to-defaults is
  refused.
- The cron scheduler itself defers to v0.6. In v0.5.0 `ract memory
  init` invokes `run_once` once; module_09 wires the CLI verb.

**Failure records.** Land `src/ract/memory/failure_records.py`:

- `FailureRecord` frozen dataclass with `function`,
  `input_token_count`, `output_token_count`, `failure_type` (closed
  vocabulary of 12 kinds), `resolution_level_reached` (closed
  vocabulary of 5 levels), `timestamp`. No prompt / response
  content by design (Lateral Chain branch C, module_08.md PRE):
  privacy invariant is enforced by the type itself.
- `write(record, root)` appends one JSONL line to
  `.rack/failures/records.jsonl`. `read_all(root)` returns the list;
  malformed lines raise with line numbers.
- `aggregate(root, window_days=7, current_budgets=None)` groups
  records by `(function, failure_type)` inside the window, produces
  a `NarrowingProposal` per `(function, field_name)` pair whose
  count reached `REPEATED_FAILURE_THRESHOLD` (3), and multiplies
  the reference current value by `NARROWING_STEP_FRACTION` (0.8) to
  yield the proposed new value. When the caller supplies
  `current_budgets`, the reference is that map; otherwise the
  aggregator falls back to the maximum `input_token_count` observed
  at failure (a conservative fallback that still guarantees the
  always-narrowing invariant).
- `NarrowingProposal.__post_init__` refuses widening at construct
  time: `new_value > reference_current_value` raises `ValueError`.
  The invariant holds regardless of caller input.
- `failure_from_phase_record(phase_record)` converts a module_07
  `PhaseRecord` with `outcome == "raised"` into a `FailureRecord`.
  This closes module_07 POST inbound constraint 1: the composition
  runner's phase records are the primary composition-layer failure
  signal and the aggregator consumes them without a separate
  failure taxonomy.
- `append_applied_narrowing(proposal, root, ...)` writes one line
  to `.rack/failures/applied_narrowings.jsonl` per applied
  narrowing. Lateral Chain branch E (module_08.md PRE): every
  applied narrowing is auditable.
- Automatic nightly application defers to v0.6; module_09 wires
  the manual `ract memory apply-narrowings` CLI verb.

**Repo fingerprint.** Land `src/ract/memory/repo_fingerprint.py`:

- `RepoFingerprint` frozen dataclass with `avg_function_tokens`,
  `avg_import_depth`, `lsp_response_time_p50_ms`,
  `lsp_response_time_p95_ms`, `test_suite_runtime_seconds`,
  `commit_frequency_per_week`, `recorded_at`, `schema_version`.
- `compute(root, symbols, graph, lsp_response_times_ms,
  test_suite_runtime_seconds, commit_timestamps, now)` builds a
  fingerprint. Every non-repo-derived input has a `None` default:
  the fresh-repo path (Lateral Chain branch D, module_08.md PRE)
  populates `-1` sentinels for LSP latency and test runtime; the
  mapper treats `-1` as "no signal, use module_01 spec defaults".
- `retrieval_defaults_from_fingerprint(fingerprint)` is pure:
  same fingerprint always produces the same defaults. Second Pass
  Q3 invariant. Sentinels collapse to `None` on the returned
  `RetrievalDefaults`; the retrieve primitive keeps its own
  module_05 default when a field is `None`.
- `write(fp, root)` and `read(root)` follow the same atomic-
  replace + strict-schema pattern as the capability record.

## Consequences

- The four contract-function budgets keep their spec-time defaults
  until a probe run writes a capability record. First `ract memory
  init` bootstraps the record; subsequent invocations narrow only
  if the observed capability shrunk (widening is refused at the
  module_01 helper).
- The failure aggregator never produces a proposal below the
  `REPEATED_FAILURE_THRESHOLD` count. A one-off failure does not
  narrow the budget; three failures on the same
  `(function, failure_type)` pair inside a 7-day window do. The
  threshold and the window are constants exposed for module_09's
  CLI to surface at `apply-narrowings` time.
- Probes cost tokens too. The scheduler shipped in v0.5.0 is
  synchronous and invoked from `ract memory init`; the weekly
  cadence + provider-rate-limit interaction defers to v0.6 with
  the cron scheduler. Lateral Chain branch A of module_08.md PRE
  is closed as a "synchronous now, cron later" contract.
- Deterministic probe fixtures reuse
  `ract.memory.functions.testing.MockProvider` per module_06
  POST inbound constraint 2. A probe run against a live provider
  is documented but not automated in the shipped test suite; the
  manual smoke lands in the module_08 status log.
- The `FailureRecord` shape excludes prompt / response content by
  design. A future request to attach content is a schema bump +
  operator handshake; the type refuses today's mistake at the
  construct site.
- The fingerprint mapper heuristics (600s cache TTL for slow LSPs,
  800-token per-symbol target for large functions, 15-symbol
  neighborhood cap for high import depth) are landing-pass tunable.
  A v0.6 hardening pass will migrate these to a repo-configurable
  file if operator feedback demands it.

## References

- Master spec: `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`
  §Self-adjustment, §Signals item 10, §Repo fingerprint.
- Module map: `_BUILD/ract_v0.5.0_memory_discipline/module_08.md`.
- Budget accountant + narrowing floor: ADR-0031.
- Failure-record shape (borrowed): ALM module_05 event-trace
  substrate under `_BUILD/ract_v0.4.0_antilazy/module_05.md`.
- Release-shape checkpoint precedent: substrate module_08 under
  `_BUILD/ract_v0.4.0_substrate/module_08.md`.
- Needle-in-a-haystack public benchmark shape: Greg Kamradt's
  original blog post shape (cited but not vendored).
