# module_08 — Self-adjustment probes

**Origin.** MEMORY DISCIPLINE §Self-adjustment and §Signals item 10.
Budgets in v0.5.0 default to spec-time values; measured behavior on the
actual provider is what should drive them. This module ships the three
probe suites (needle, coherence, adherence), the failure-record
aggregator, and the per-repo fingerprint. The nightly recompilation
loop and the drift detector defer to v0.6 per §Bounded scope.

**Intent.** Land `src/ract/memory/probes/{__init__,needle,coherence,
adherence,scheduler}.py`, `src/ract/memory/failure_records.py`, and
`src/ract/memory/repo_fingerprint.py`. Probe results feed a
`model_capability` record at `.rack/probes/capability.json`; budgets
derive from this record when populated, from the module_01 defaults
otherwise. Failure records aggregate in `.rack/failures/records.jsonl`.
Repo fingerprint persists at `.rack/fingerprint/repo.json`.

## Steps

1. **Read** the prior surfaces this module feeds into.
   - `src/ract/memory/budget.py` and `budget_registry.py` (module_01)
     — probe-derived budgets narrow the defaults via
     `apply_runtime_narrowing`.
   - `src/ract/memory/events.py` (module_01) — the
     `probe.evaluated` emitter helper.
2. **Add** `src/ract/memory/probes/needle.py`:
   - `NeedleProbe` — inserts a specific fact at various depths in
     context of increasing size; asks a question requiring the fact;
     measures recall. Depths tested: 5% / 25% / 50% / 75% / 95%.
     Context sizes tested: 2k / 4k / 8k / 16k tokens.
   - `run(provider: Provider) -> NeedleProbeReport`.
   - `NeedleProbeReport(dataclass, frozen)` — `recall_at_depth: dict[
     float, dict[int, bool]]`, `usable_context_window: int`.
3. **Add** `src/ract/memory/probes/coherence.py`:
   - `CoherenceProbe` — provides long context with a subtle
     inconsistency; asks the model to identify it.
   - `run(provider: Provider) -> CoherenceProbeReport`.
   - `CoherenceProbeReport(dataclass, frozen)` — `identified_at_size:
     dict[int, bool]`, `reasoning_quality_bound: int`.
4. **Add** `src/ract/memory/probes/adherence.py`:
   - `AdherenceProbe` — provides long context with a specific
     instruction at beginning; asks a question requiring the
     instruction.
   - `run(provider: Provider) -> AdherenceProbeReport`.
   - `AdherenceProbeReport(dataclass, frozen)` —
     `instruction_persistence_at_size: dict[int, bool]`,
     `persistence_bound: int`.
5. **Add** `src/ract/memory/probes/scheduler.py`:
   - `ProbeScheduler` — runs the three probes at a configurable
     cadence (default: on `ract memory init`, weekly thereafter).
   - `write_capability_record(reports: ProbeReports) -> None` —
     writes `.rack/probes/capability.json` with the reduced
     `model_capability` shape.
   - `read_capability_record() -> ModelCapability | None`.
6. **Add** `src/ract/memory/failure_records.py`:
   - `FailureRecord(dataclass, frozen)` — `function: str`,
     `input_token_count: int`, `output_token_count: int`,
     `failure_type: Literal[<enum>]`, `resolution_level_reached:
     Literal[<enum>]`, `timestamp: int`.
   - `write(record: FailureRecord, root: Path = <default>) -> None`
     — appends to `.rack/failures/records.jsonl` (JSONL, one record
     per line).
   - `aggregate(root: Path, window_days: int = 7) -> AggregateReport`
     — reads the JSONL, groups by function + failure_type, produces
     a per-function narrowing proposal (always narrowing, never
     widening).
   - The aggregator emits proposals; nightly automatic application
     defers to v0.6. This module ships the aggregator + a manual
     `ract memory apply-narrowings` CLI verb (module_09 wires the
     verb into the CLI surface).
7. **Add** `src/ract/memory/repo_fingerprint.py`:
   - `RepoFingerprint(dataclass, frozen)` — `avg_function_tokens:
     float`, `avg_import_depth: float`,
     `lsp_response_time_p50_ms: int`,
     `lsp_response_time_p95_ms: int`,
     `test_suite_runtime_seconds: int`,
     `commit_frequency_per_week: float`.
   - `compute(root: Path, symbols: SymbolIndex, graph: GraphIndex)
     -> RepoFingerprint`.
   - `write(fingerprint: RepoFingerprint, root: Path = <default>)
     -> None` — writes `.rack/fingerprint/repo.json`.
   - `read(root: Path = <default>) -> RepoFingerprint | None`.
   - Repo defaults derive from the fingerprint via a small mapper
     (repos with slow LSPs get more aggressive caching; repos with
     large functions get larger neighborhood budgets). The mapper
     is a pure function; the retrieval defaults it feeds are
     applied via `apply_runtime_narrowing` at `retrieve` invocation
     time (module_09 wires this).
8. **Tests** — new files under `tests/memory/`:
   - `tests/memory/test_probes_needle.py` — needle probe against a
     mock provider that returns the fact at depths [5%, 25%, 50%]
     but misses [75%, 95%]; asserts `usable_context_window` reflects
     the observed cliff.
   - `tests/memory/test_probes_coherence.py` — coherence probe
     against a mock provider that identifies the inconsistency at
     sizes ≤ 4k and misses at 8k+; asserts
     `reasoning_quality_bound == 4000`.
   - `tests/memory/test_probes_adherence.py` — adherence probe with
     equivalent behavior model.
   - `tests/memory/test_probes_scheduler.py` — scheduler runs the
     three probes; the capability record is written and readable;
     a subsequent budget query narrows against the capability.
   - `tests/memory/test_failure_records.py` — record roundtrip
     write/read; aggregator over a synthetic 7-day window produces
     narrowing proposals with the always-narrowing invariant.
   - `tests/memory/test_repo_fingerprint.py` — fingerprint compute
     against the fixture repo produces expected values within
     tolerance; write/read roundtrip clean.
9. **Docs:**
   - Add ADR-0038: "Probe-derived budgets narrow spec defaults."
     Cover rejected alternatives: static spec-time budgets forever
     (spec drift as providers evolve), full model-side self-tuning
     (opaque, no attribution), operator-only manual tuning (no
     signal).
   - Add a new section to `docs/ARCHITECTURE.md`: "Self-adjustment
     probes (v0.5.0 memory discipline)." Cross-link to master spec
     §Self-adjustment.

## Lateral Chain pass (PRE-build)

**Branches:**

- A: **Probe cost.** Running three probe suites against a live
  provider costs budget. Merge branch — probes run on `ract memory
  init` (once per repo) and then weekly on a scheduled cadence; the
  scheduler respects the provider's rate limits via the existing
  `rate_limiter`. Carry forward.
- B: **Probe accuracy against a mock provider.** The tests use a
  mock; real behavior may diverge. Merge branch — the DoD includes
  a manual smoke against one live provider at close (documented,
  not automated); the scheduler skips this smoke in CI.
- C: **Failure record privacy.** Records include token counts and
  failure types but should NOT include raw prompt content. Merge
  branch — `FailureRecord` explicitly excludes prompt/response
  content by construction; the type has no such field. A future
  request to include content is a schema bump plus operator
  handshake.
- D: **Repo fingerprint on a fresh repo.** Fresh repo has no LSP
  response history and no test suite runtime. Merge branch —
  `compute` returns a fingerprint with `lsp_response_time_p50_ms:
  -1` sentinel and the mapper treats -1 as "no signal, use spec
  defaults." Carry forward.
- E: **Narrowing proposal application.** The aggregator emits
  proposals; the manual apply verb takes operator intent.
  Automated application defers to v0.6. Merge branch — the manual
  verb explicitly logs every applied narrowing to
  `.rack/failures/applied_narrowings.jsonl` for later audit.

**Prune:** keep A, B, C, D, E. All five change intent shape.

**Up-intent verify:** sharper. A closes the probe-cost worry; B
closes the mock-divergence worry; C closes the privacy worry; D
closes the fresh-repo worry; E closes the audit-trail worry.

## Depth Chain pass (PRE-build)

**Load-bearing assumption.** The three probes distinguish "the
provider works well at this size" from "the provider degrades at
this size" on the current provider mix. If all three probes return
green at every tested size, the capability record simply matches the
spec defaults and no narrowing fires — that is the correct behavior
on a strong provider. If probes return red at 8k+, budgets narrow
accordingly.

**Core dependency.** module_01's `apply_runtime_narrowing` is the
enforcement point. Every probe-derived narrowing writes through
this function; a widening attempt is refused per module_01's
invariant.

**Leaves.**

- **Depth 4 leaf (a):** `src/ract/memory/probes/{__init__,needle,
  coherence,adherence,scheduler}.py`,
  `src/ract/memory/failure_records.py`,
  `src/ract/memory/repo_fingerprint.py` all import; `pytest -q
  tests/memory/test_probes_needle.py
  tests/memory/test_probes_coherence.py
  tests/memory/test_probes_adherence.py
  tests/memory/test_probes_scheduler.py
  tests/memory/test_failure_records.py
  tests/memory/test_repo_fingerprint.py` all green.
- **Depth 4 leaf (b):** the capability record roundtrips; a
  probe-derived narrowing that would widen a default raises
  `WideningRefusedError`.
- **Depth 4 leaf (c):** fingerprint compute on the fixture repo
  produces the expected values within tolerance; the mapper handles
  the -1 sentinel.
- **Depth 4 leaf (d):** ADR-0038 exists; `docs/ARCHITECTURE.md` has
  a new "Self-adjustment probes" section.

## Reasoning Endpoints for scoping

**Producer:** NVIDIA `reason_agentic` (MiniMax M2.7). Role: draft
the three probe designs, the scheduler, the aggregator, and the
fingerprint mapper.

**Reviewer:** Google Gemini flash reasoning function (cross-family
from MiniMax). Documented fallback: an OpenRouter reasoning function cross-family from Qwen3 Coder (operator selects the specific function from the current OpenRouter catalog at dispatch time).

**Why the pair provides blind-spot diversity.** MiniMax designs the
measurement machinery; Gemini flash reasoning reads the measurement
semantics and tests them against edge cases. Concrete review
question: "Does the needle probe's cliff-detection actually
distinguish a real capability boundary from a transient miss
(model noise), or does one bad response at depth 75% inflate the
narrowing proposal past what the signal supports?"

## Second Pass discipline

After the first-build subagent lands the code plus tests and the DoD
is boolean-passing, the diff plus master-spec §Self-adjustment quote
plus the probe test files go to Google Gemini flash reasoning
function for skeptical review. Same reviewer named in the scoping
section. Fallback: an OpenRouter reasoning function cross-family from Qwen3 Coder (operator selects the specific function from the current OpenRouter catalog at dispatch time).

**Adversarial questions the reviewer is asked:**

1. Does the needle probe's cliff-detection distinguish real
   capability boundary from noise? Name any code path where one bad
   response at a depth inflates the narrowing beyond the signal.
2. The failure aggregator groups by function and failure_type. If
   one workflow-invalid failure (e.g., a WorkOrder with a
   malformed request_type) dominates the aggregate, does the
   narrowing proposal correctly attribute it to a data-shape issue
   rather than a budget issue?
3. The fingerprint mapper feeds retrieval defaults per repo. Is the
   mapping pure (same fingerprint always produces same defaults),
   or does the mapper carry hidden state that could drift results
   run-to-run?
4. `write_capability_record` writes JSON. If the write is
   interrupted mid-file (e.g., process kill), the next read gets
   corrupted JSON. Does the writer use atomic-replace (write tmp,
   fsync, rename) or naive `open('w')`?

**Two possible outcomes.** Same protocol as module_01-07.

## Lateral Chain pass (POST-audit)

Applied against the FINISHED module + Second Pass verdicts.

**Branches:**

- **POST-A: Reviewer-response-quality asymmetry across dispatch
  paths.** The Second Pass first-dispatch (`reason_nemotron_ultra`
  via OpenRouter, prompt WITHOUT source bundle) returned four
  entirely hallucinated verdicts referencing file:line locations
  that do not exist in the shipped surface. The re-dispatch (SAME
  reviewer, prompt WITH source bundle inline) returned four
  accurate verdicts with correct file:line evidence. Load-bearing
  lesson for module_09+: Second Pass prompts MUST inline the actual
  source under review, not a description-only summary of the
  surface. Merge branch — carry forward as an inbound constraint
  for module_09.
- **POST-B: Stale-reference bypass of always-narrowing invariant.**
  SP Q4 Orthogonal 3: `NarrowingProposal.__post_init__` enforces
  `new_value <= reference_current_value` at construction, but the
  reference itself may be stale by apply time (aggregator's
  `current_budgets` map might disagree with the live declaration).
  Folded fix inline: added :class:`StaleReferenceError` +
  :func:`validate_proposal_against_live_value` +
  :func:`append_applied_narrowing(..., live_current_value=...)`
  parameter. Regression tests
  `test_validate_proposal_against_live_value_refuses_stale_reference`
  and `test_append_applied_narrowing_refuses_stale_live_value` pin
  the safety gate. Merge branch — closes the SP orthogonal in the
  shipped module rather than pushing the whole safety burden to
  module_09.
- **POST-C: Needle-probe reducer over-narrows on transient noise.**
  SP Q1 CONFIRMED: `_reduce_usable_context_window` breaks on the
  first size where any depth misses. Transient miss at depth 0.95
  on the 2000-token context collapses the empirical window to 0
  and drives budgets to the floor. The shipped behavior IS the
  behavior the tests pin (the "spec scenario" test in
  `test_probes_needle.py` asserts `usable_context_window == 0` for
  exactly the hit-only-at-shallow-depths pattern). Merge branch
  as Flagged gap 1 rather than folding a noise-tolerant reducer
  today — the alternative (require k-of-n depths per size) is a
  policy change that deserves an ADR-shape decision, not a rushed
  inline fix.
- **POST-D: PhaseRecord bridge discards token counts.**
  SP Orthogonal 4: `failure_from_phase_record` defaults
  `input_token_count` and `output_token_count` to 0 because the
  shipped :class:`~ract.memory.composition_runner.PhaseRecord`
  shape does not carry them. Downstream: the aggregator's
  fallback-reference path (when `current_budgets=None`) tracks
  the max observed `input_token_count`, which for phase-derived
  failures is always 0 → reference <= 0 → the failure drops from
  narrowing consideration. Module_09 is the natural home for
  populating token counts on the PhaseRecord shape (its provider
  adapter has the accountant in scope). Prune from POST-audit
  action, carry forward as inbound constraint for module_09.
- **POST-E: Aggregator fallback reference inflates upward.** SP
  Orthogonal 2: when `current_budgets` is `None`, the aggregator
  uses max failure-time `input_token_count` as the reference.
  A failure with `input_token_count=5000` implies the assembled
  input was 5000, but the DECLARED budget that refused may have
  been 2000. The proposal narrows against 5000 → 4000, weaker
  than the "narrow the actual 2000 budget" the aggregator should
  fire. Mitigation: strongly prefer `current_budgets` from the
  caller. Prune as Flagged gap 3 — the fix is a caller
  convention, not an inline code change today.

**Prune:** keep A, B, C, D, E. All five change how a future
maintainer touches the module — A affects the review process
itself; B lands an inline safety gate the caller MUST invoke; C
and E are gaps that need a decision, not a rewrite; D names a
concrete module_09 wiring surface.

**Up-intent verify:** sharper. A closes a latent Second Pass
quality risk that would have shipped a mis-reviewed module (the
first dispatch's hallucinated verdicts would have been accepted
as valid if the source-bundle re-dispatch had not fired). B
closes the stale-reference bypass in the shipped code. C, D, E
name concrete v0.6 hardening + module_09 inbound constraints.

## Depth Chain pass (POST-audit)

Applied against the FINISHED module.

**Load-bearing assumption from PRE-build:** "The three probes
distinguish 'the provider works well at this size' from 'the
provider degrades at this size' on the current provider mix. If
all three probes return green at every tested size, the capability
record simply matches the spec defaults and no narrowing fires."

**CONFIRMED as delivered** — with a POST-C-flagged asymmetry: the
probes DO distinguish these two conditions cleanly at the reducer
level, but the reducer's collapse-to-zero-on-any-miss shape
(needle.py `_reduce_usable_context_window` at
`src/ract/memory/probes/needle.py:161-179`) is stricter than the
spec text suggests. A single transient miss at deep depth on the
smallest size collapses the window to 0. Test
`test_run_cliff_detection_pins_window_to_last_size_where_all_depths_hit`
pins the collapse-to-zero behavior; the test's assertion IS the
current contract. A noise-tolerant reducer defers to v0.6 per
POST-C.

**Core dependency from PRE-build:** "module_01's
`apply_runtime_narrowing` is the enforcement point. Every probe-
derived narrowing writes through this function; a widening
attempt is refused per module_01's invariant."

**CONFIRMED as delivered** with additional inline gate: the
shipped aggregator emits `NarrowingProposal` records that refuse
widening at construct time (`failure_records.py:187-192`), plus
the new POST-B stale-reference gate
(`failure_records.py:validate_proposal_against_live_value`)
re-checks at apply time. Two layers of defense; both feed the
module_01 helper.

**Leaves.**

- **Depth 4 leaf (a):** `src/ract/memory/probes/{__init__,needle,
  coherence,adherence,scheduler}.py` +
  `src/ract/memory/failure_records.py` +
  `src/ract/memory/repo_fingerprint.py` all import; `pytest -q
  tests/memory/test_probes_needle.py
  tests/memory/test_probes_coherence.py
  tests/memory/test_probes_adherence.py
  tests/memory/test_probes_scheduler.py
  tests/memory/test_failure_records.py
  tests/memory/test_repo_fingerprint.py` runs 85 tests green (11
  needle + 11 coherence + 11 adherence + 12 scheduler + 27 failure
  records + 13 repo fingerprint after SP fold; +4 regression tests
  landed inline for POST-B). Up-chain verify: parent Intent "land
  three probe suites plus failure aggregator plus fingerprint"
  delivered.
- **Depth 4 leaf (b):** capability record roundtrips at
  `src/ract/memory/probes/scheduler.py:181-215` via tmp + fsync +
  `os.replace`; malformed JSON at `scheduler.py:230-244` raises
  `ValueError`; unsupported schema version raises `ValueError`.
  Tests `test_write_and_read_capability_record_roundtrip`,
  `test_read_capability_record_malformed_json_raises`,
  `test_read_capability_record_wrong_schema_version_raises` pin
  each path. Up-chain verify: parent Intent "atomic capability
  record with strict schema" delivered.
- **Depth 4 leaf (c):** repo fingerprint handles the fresh-repo
  path at `repo_fingerprint.py:132-150`; sentinels (`-1`) flow
  through the pure mapper at `repo_fingerprint.py:262-296` and
  collapse to `None` on the returned
  :class:`RetrievalDefaults`. Tests
  `test_compute_fresh_repo_returns_sentinels`,
  `test_mapper_no_signal_returns_all_none`,
  `test_mapper_is_pure_same_input_same_output` pin each path.
  Up-chain verify: parent Intent "fresh-repo fingerprint + pure
  mapper" delivered.
- **Depth 4 leaf (d):** `docs/ADRs/ADR-0038-self-adjustment-
  probes.md` exists; `docs/ARCHITECTURE.md` has a new "Self-
  adjustment probes (v0.5.0 memory discipline)" section (76-line
  insertion). Up-chain verify: parent Intent "documented 3-probe
  v0.5 scope + v0.6 deferral rationale" delivered.

## Inbound constraints for module_09

Module_08 surfaces the following for module_09 to honor at its own
POST time:

1. **Module_09 MUST inline the actual source under review in every
   Second Pass prompt.** POST-A: description-only prompts produce
   hallucinated verdicts. The reviewer needs the code, not just
   the shape.
2. **Module_09 MUST pass `live_current_value` to
   `append_applied_narrowing`.** POST-B: the shipped safety gate
   only fires when the caller supplies the live budget. The
   `apply-narrowings` CLI verb MUST read the live declaration from
   `budget_registry.get(function)` and pass the relevant field
   value.
3. **Module_09 SHOULD extend PhaseRecord with token counts.**
   POST-D: the shipped `failure_from_phase_record` bridge defaults
   token counts to 0, dropping phase-derived failures from
   narrowing consideration under the fallback-reference path. The
   provider adapter has the accountant in scope; wiring
   `input_token_count=accountant.used()` into the emitted
   PhaseRecord (module_07's shape) closes the signal loss.
4. **Module_09 SHOULD invoke `run_all_probes` from `ract memory
   init`.** Master spec §Self-adjustment: probes fire on init
   and (in v0.6) on a weekly cron. The `ProbeScheduler.run_once`
   method is the entry point; the module_09 CLI verb wraps it.
5. **Module_09 SHOULD supply `current_budgets` to
   `aggregate()`.** POST-E: the fallback reference (max observed
   `input_token_count`) inflates upward and weakens the narrowing
   signal. Callers with access to `budget_registry` (module_09
   does) MUST pass the live map.
6. **Module_09 SHOULD invoke `retrieval_defaults_from_fingerprint`
   at retrieve setup.** The pure mapper is ready; module_09 wires
   it into `retrieve()` invocation defaults per master spec §Repo
   fingerprint. Fresh-repo sentinels collapse to `None` so the
   retrieve primitive keeps its module_05 defaults.

## Definition of Done

- `src/ract/memory/probes/{__init__,needle,coherence,adherence,
  scheduler}.py`, `src/ract/memory/failure_records.py`,
  `src/ract/memory/repo_fingerprint.py` all exist with the API
  listed in steps 2-7.
- Capability record writes to `.rack/probes/capability.json`;
  atomic-replace on write.
- Failure records append to `.rack/failures/records.jsonl`;
  aggregator produces narrowing proposals with the always-narrowing
  invariant.
- Repo fingerprint writes to `.rack/fingerprint/repo.json`;
  handles the -1 sentinel for a fresh repo.
- `pytest -q tests/memory/test_probes_needle.py
  tests/memory/test_probes_coherence.py
  tests/memory/test_probes_adherence.py
  tests/memory/test_probes_scheduler.py
  tests/memory/test_failure_records.py
  tests/memory/test_repo_fingerprint.py` all green.
- `ruff check src/ract/memory/`, `mypy src/ract/memory/`, and full
  `pytest -q` all clean.
- ADR-0038 exists; `docs/ARCHITECTURE.md` has a new "Self-adjustment
  probes" section.
- Manual live-provider smoke run documented in the module close
  status log.
- Closed-IP wordlist scan: zero hits.
- Second Pass complete.

## Reference sources

- MEMORY DISCIPLINE spec §Self-adjustment, §Bounded scope, §Signals
  item 10.
- Needle-in-a-haystack pattern: Greg Kamradt's original public
  benchmark shape.
- ALM module_05 (`_BUILD/ract_v0.4.0_antilazy/module_05.md`) for
  the event-trace-as-substrate pattern the aggregator mirrors.
- Substrate module_08 (`_BUILD/ract_v0.4.0_substrate/module_08.md`)
  precedent for release-shape checkpoint files.

## Flagged gaps (to log at close)

1. **Needle-probe reducer over-narrows on transient noise.**
   POST-C / SP Q1 CONFIRMED. `_reduce_usable_context_window`
   collapses to 0 on any depth miss at the smallest size. A
   single transient miss at depth 0.95 on the 2000-token context
   drives budgets to the floor. v0.6 hardening: introduce a
   noise-tolerant reducer (require k-of-n depths per size, or
   require 2 consecutive clean sizes before accepting a new
   floor) behind a config flag; keep the current strict reducer
   as the default until the alternative is validated. Owner:
   v0.6 self-adjustment hardening.

2. **Capability-record tmp file leaks on SIGKILL.** POST /
   SP Q4 PARTIAL. `write_capability_record`'s exception branch
   cleans up the tmp file on Python exceptions but SIGKILL /
   power-loss between `mkstemp` and `try` leaves the tmp file
   orphaned in `.rack/probes/`. Does NOT corrupt the target
   (atomic-replace protects it). v0.6 hardening: register an
   `atexit` handler or sweep orphaned `.tmp` files at the next
   `write_capability_record` invocation. Owner: v0.6.

3. **Aggregator fallback reference inflates upward.** POST-E /
   SP Orthogonal 2. When `current_budgets` is `None`, the
   fallback uses max failure-time `input_token_count`, which is
   larger than the declared budget that actually refused. The
   proposed narrowing is weaker than warranted. Mitigation:
   callers with access to the live budget registry (module_09)
   MUST pass `current_budgets`. v0.6 hardening: consider making
   `current_budgets` non-optional or storing the DECLARED budget
   inside :class:`FailureRecord` at emission time (schema bump).
   Owner: v0.6.

4. **PhaseRecord bridge discards token counts.** POST-D / SP
   Orthogonal 4. `failure_from_phase_record` defaults token
   counts to 0 because
   :class:`~ract.memory.composition_runner.PhaseRecord` does not
   carry them today. Module_09's provider adapter has the
   accountant in scope and is the natural home for the
   extension. Owner: module_09.

5. **Coherence probe uses a two-statement contradiction rather
   than a semantic-diff check.** SP Orthogonal 2 (coherence
   variant). Some models "correct" the contradiction silently,
   yielding a pass that masks reasoning degradation. v0.6
   hardening: add a semantic-diff check that requires the model
   to name the contradiction category (day / date / room) not
   just repeat both tokens. Owner: v0.6.

6. **Adherence probe places instruction at start only.** SP
   Orthogonal 3 (adherence variant). Mid-context and end-context
   instruction persistence are not tested; the shipped metric is
   one-dimensional. v0.6 hardening: parametrize instruction
   placement (start / middle / end) and report per-placement
   persistence. Owner: v0.6.

7. **`repo_fingerprint.compute` default path calls `git log`.**
   SP Orthogonal 5. The default path is impure (depends on
   filesystem `.git`, git binary availability, working-tree
   staleness). Mitigated by explicit `commit_timestamps`
   parameter for test injection; the mapper itself
   (`retrieval_defaults_from_fingerprint`) remains pure. v0.6
   hardening: extract the git invocation to a small helper the
   caller injects when purity is required. Owner: v0.6.

8. **Second Pass prompts must inline source under review.**
   POST-A. The first-dispatch response (description-only prompt)
   returned four entirely hallucinated verdicts. The re-dispatch
   (same reviewer, source bundle inline) returned four accurate
   verdicts. Every subsequent module MUST inline the actual
   source, not a shape summary. Owner: module_09 pipeline
   dispatch convention.

## Manual live-provider smoke

Deferred to module_10 release close per Lateral Chain branch B
(module_08.md PRE) — the shipped tests exercise every probe path
against the deterministic MockProvider (module_06 POST inbound
constraint 2). A live-provider run against one operator-selected
provider lands at release close with results appended to the
close status log.
