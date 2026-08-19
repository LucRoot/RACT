# module_09 — Integration with existing RACT

**Origin.** MEMORY DISCIPLINE §Integration surface with existing RACT
and §Signals items 11-13. Modules 01-08 land the memory-discipline
substrate as parallel surfaces; module_09 wires it into the SubstrateLoop
the executor-adapter shim constructs, extends the closed EventKind
vocabulary with the seven new kinds, extends the Rootknot generator
payload with `retrieval_attestation`, and extends ALM Gates G6 and G7
to consume the `edit` function's output.

**Intent.** Land the integration wiring. `SubstrateLoop.run_step` reads
`SubstrateStepSpec.metadata["retrieval_bundle"]` when populated and
threads it into the step runner. The seven new event kinds bump
`EventKind` in `src/ract/trace/events.py`. Rootknot's generator payload
carries `retrieval_attestation` optionally; older sidecars verify
under the compatibility reader. ALM Gate G6 (under-edit closure) and
G7 (companion provider) both accept a `CandidateDiff` from module_06's
`edit` function. The `ract retrieval query`, `ract memory init`, and
`ract memory apply-narrowings` CLI verbs land.

## Steps

1. **Read** the existing integration surfaces.
   - `src/ract/executor/loop.py` — `SubstrateLoop.run_step` signature
     and the `SubstrateStepSpec.metadata` field.
   - `src/ract/trace/events.py` — the closed `EventKind` Literal
     alias.
   - `src/ract/core/rootknot.py` — the three-signature schema and the
     generator signature's payload shape.
   - `src/ract/antilazy/pre_commit.py` — `enforce_g6`, `enforce_g7`
     signatures.
   - `src/ract/cli.py` — `CLI_VERBS` tuple and the verb dispatch
     pattern.
2. **Extend** `src/ract/trace/events.py::EventKind`:
   - Add: `budget.declared`, `budget.exceeded`,
     `retrieval.requested`, `retrieval.satisfied`,
     `retrieval.cascaded`, `retrieval.refused`, `probe.evaluated`.
   - Update `LEGAL_EVENT_KINDS` (auto-recomputes from `get_args`).
   - Bump `docs/EVENTS.md` schema version and document each kind.
3. **Wire** `SubstrateLoop.run_step` to read
   `SubstrateStepSpec.metadata["retrieval_bundle"]`:
   - When present, the loop passes the bundle into the step runner's
     invocation context.
   - Emit `retrieval.satisfied` with `bundle.total_tokens` and
     `bundle.budget_used_pct` at step start.
   - When absent, the loop proceeds as today (deterministic
     non-model step or a legacy step that pre-dates memory
     discipline).
4. **Extend** `src/ract/core/rootknot.py`:
   - Generator payload gains an optional `retrieval_attestation:
     Digest | None` field (SHA-256 of the retrieval bundle the step's
     model call consumed).
   - `make_rootknot_v3` accepts the field via a new
     `retrieval_attestation: Digest | None = None` kwarg.
   - Compatibility reader path: an older sidecar without the field
     verifies as today; a v3 sidecar with the field verifies with the
     field included in the canonical bytes.
   - No new signature, no schema-version bump.
5. **Extend** `src/ract/antilazy/pre_commit.py::enforce_g6`:
   - `enforce_g6(diff: CandidateDiff, plan: ChangePlan)` — check
     that every file the diff touches appears in
     `plan.load_manifest`; raise `LazinessViolatedError` with
     `kind="under_edit_closure_gap"` when it does not.
6. **Extend** `src/ract/antilazy/pre_commit.py::enforce_g7`:
   - `enforce_g7(diff: CandidateDiff, companion: Provider)` —
     issue a companion-provider review of the diff; raise
     `LazinessViolatedError` with `kind="companion_flagged"` on a
     negative verdict.
7. **Add** CLI verbs to `src/ract/cli.py`:
   - `ract memory init <path>` — invokes
     `symbol_builder.initial_build` + `graph_builder.initial_build`
     + `semantic_builder.initial_build` + probe scheduler first-run
     against the repo.
   - `ract memory apply-narrowings [--dry-run]` — invokes the
     failure aggregator (module_08) and applies proposed narrowings.
   - `ract retrieval query <query> [--budget N] [--format
     full|body|sig|summary] [--strategy relevance|complete|core]` —
     invokes the retrieve primitive against the three indexes and
     prints the resulting bundle.
   - Extend `CLI_VERBS` tuple with `memory`.
8. **Wire** the module_05 retrieve primitive to consume the real
   event sink:
   - `src/ract/memory/events.py` (module_01) currently uses a null
     sink; module_09 swaps for the `JsonlEventWriter` the SubstrateLoop
     constructs. The swap is a wiring change in the loop
     constructor; no change to `retrieve.py`'s emit calls.
9. **Add** the fixture-repo integration path for the smoke script from
   module_01 (`scripts/memory/smoke_budget_defaults.py`) to use the
   tiny_repo fixture from module_02.
10. **Tests** — new files under `tests/executor/` and `tests/memory/`:
    - `tests/executor/test_substrate_loop_retrieval_wiring.py` —
      SubstrateLoop with a `SubstrateStepSpec.metadata["retrieval_
      bundle"]` set threads the bundle into the runner; `retrieval.
      satisfied` fires.
    - `tests/memory/test_rootknot_retrieval_attestation.py` —
      sacred-spine test named in master spec: an older sidecar
      without the field verifies (`test_older_sidecar_still_verifies`);
      a v3 sidecar with the field verifies and its
      canonical_bytes includes the field.
    - `tests/memory/test_g6_edit_under_edit_closure.py` — a
      CandidateDiff that touches a file not in `plan.load_manifest`
      raises `LazinessViolatedError` with the expected kind.
    - `tests/memory/test_g7_edit_companion_review.py` — a
      CandidateDiff plus a companion provider that returns a
      negative verdict raises `LazinessViolatedError` with the
      expected kind.
    - `tests/memory/test_cli_memory_verbs.py` — each new CLI verb
      resolves through `--help`; a smoke invocation of `memory init`
      against the fixture repo completes with no errors.
    - `tests/memory/test_event_kinds_extended.py` — the seven new
      kinds are members of `LEGAL_EVENT_KINDS`.
11. **Docs:**
    - Add ADR-0039: "Memory-discipline integration with SubstrateLoop
      and ALM." Cover rejected alternatives: parallel-loop-for-memory
      (two loops competing), replace-SubstrateLoop-entirely (breaks
      v0.4.x invariants), memory-discipline-outside-the-loop (breaks
      Rootknot attestation).
    - Update `docs/ARCHITECTURE.md`'s existing SubstrateLoop section
      to name the retrieval-bundle wiring.
    - Bump `docs/EVENTS.md` schema version and document each of the
      seven new kinds.

## Lateral Chain pass (PRE-build)

**Branches:**

- A: **EventKind bump breaks the golden hash gate.** Adding kinds
  changes the source-tree hash. Merge branch — the bump is
  intentional and expected; module_10 re-locks the golden hash after
  the integration lands. Carry forward as a module_10 dependency.
- B: **Rootknot compatibility reader regression.** Older sidecars
  must continue to verify. Merge branch — the sacred-spine test
  `test_older_sidecar_still_verifies` runs against a corpus of v1,
  v2, v3-without-attestation sidecars from the fixtures directory;
  every one must verify. Carry forward.
- C: **G6 under-edit closure interaction with legacy edit paths.**
  The existing `LoopController` runs a v0.3-era milestone path that
  does not produce `CandidateDiff`. Merge branch — G6's new
  signature accepts `CandidateDiff | None`; when None, G6 falls back
  to its existing under-edit closure check against the workspace
  snapshot. Carry forward. This is the load-bearing wiring that
  keeps v0.4.x paths intact.
- D: **G7 companion cost.** Every `edit` gets a companion review;
  double the model calls. Merge branch — G7 is gated on a
  `ract.yaml` flag `enable_g7_on_edit` (default True); operators can
  disable for pilot runs. Carry forward.
- E: **CLI verb collision.** `ract retrieval` already exists (v0.1-
  era). Merge branch — the new subverb is `ract retrieval query`;
  the existing shape stays. Carry forward.

**Prune:** keep A, B, C, D, E. All five change intent shape.

**Up-intent verify:** sharper. A closes the golden-hash worry (with
a clear module_10 handoff); B closes the compatibility-regression
worry; C closes the legacy-loop worry; D closes the G7-cost worry;
E closes the verb-collision worry.

## Depth Chain pass (PRE-build)

**Load-bearing assumption.** SubstrateLoop's `run_step` signature
does not change; only the metadata reading changes. If a caller
constructs `SubstrateStepSpec` without `metadata["retrieval_
bundle"]`, the loop proceeds as today (deterministic non-model or
legacy path). This preserves every v0.4.x caller.

**Core dependency.** The Rootknot compatibility reader path is
sacred spine. `test_older_sidecar_still_verifies` is the named test
and it must be green at every commit in this module.

**Leaves.**

- **Depth 4 leaf (a):** `src/ract/trace/events.py` extended;
  `src/ract/executor/loop.py` extended with the metadata read;
  `src/ract/core/rootknot.py` extended with the optional field;
  `src/ract/antilazy/pre_commit.py` `enforce_g6` and `enforce_g7`
  extended; `src/ract/cli.py` `CLI_VERBS` extended with `memory`;
  `pytest -q tests/executor/test_substrate_loop_retrieval_wiring.py
  tests/memory/test_rootknot_retrieval_attestation.py
  tests/memory/test_g6_edit_under_edit_closure.py
  tests/memory/test_g7_edit_companion_review.py
  tests/memory/test_cli_memory_verbs.py
  tests/memory/test_event_kinds_extended.py` all green.
- **Depth 4 leaf (b):** the sacred-spine test
  `test_older_sidecar_still_verifies` green against v1, v2,
  v3-without-attestation fixtures.
- **Depth 4 leaf (c):** every new CLI verb resolves through
  `--help`; smoke `memory init` against the fixture repo completes.
- **Depth 4 leaf (d):** ADR-0039 exists; `docs/EVENTS.md` bumped;
  `docs/ARCHITECTURE.md` SubstrateLoop section updated.

## Reasoning Endpoints for scoping

**Producer:** NVIDIA `code` (Qwen3 Coder 480B). Role: draft the
integration wiring across SubstrateLoop + events + Rootknot + ALM
gates + CLI. Qwen3 Coder navigates multi-surface Python well and
produces the exact patches this integration needs.

**Reviewer:** an OpenRouter reasoning function cross-family from Qwen3 Coder (operator selects the specific function from the current OpenRouter catalog at dispatch time) (cross-family from Qwen3
Coder). Documented fallback if OpenRouter's budget is exhausted:
Google Gemini flash reasoning function.

**Why the pair provides blind-spot diversity.** Qwen3 Coder produces
the integration patches; the OpenRouter cross-family reviewer reviews the sacred-spine
preservation (Rootknot compatibility, EventKind closed vocabulary,
SubstrateLoop signature stability). Concrete review question: "Does
the new `retrieval_attestation` field extension actually preserve
the compatibility reader path for v1/v2/v3-without-attestation
sidecars, or is there a code path where a canonical-bytes read on
an older sidecar produces a hash mismatch against its stored
signature?"

## Second Pass discipline

After the first-build subagent lands the code plus tests and the DoD
is boolean-passing, the diff plus master-spec §Integration surface
quote plus `tests/memory/test_rootknot_retrieval_attestation.py` go
to an OpenRouter reasoning function cross-family from Qwen3 Coder (operator selects the specific function from the current OpenRouter catalog at dispatch time) for skeptical review. Same reviewer
named in the scoping section. Fallback: Google Gemini flash reasoning
function.

**Adversarial questions the reviewer is asked:**

1. Does the `retrieval_attestation` extension preserve the
   compatibility reader path? Name any code path where an older
   sidecar produces a hash mismatch.
2. The seven new EventKind members bump the closed vocabulary. Does
   the LEGAL_EVENT_KINDS frozenset auto-recompute, or is there a
   hardcoded set somewhere that misses the new kinds and produces
   silent "unknown event kind" errors on write?
3. G6's new signature accepts `CandidateDiff | None`. Is the None
   fallback exercised by every legacy caller path, or does one
   caller construct a `CandidateDiff` from a legacy diff shape and
   pass it to G6 with a mismatched schema?
4. The `ract memory init` verb runs three initial builds sequentially.
   If the semantic build fails partway (e.g., embedding download
   fails), does the verb leave the repo in a partial state with two
   indexes populated and one empty, or does it clean up?

**Two possible outcomes.** Same protocol as module_01-08.

## Lateral Chain pass (POST-audit)

Second Pass reviewer (DeepSeek `deepseek-chat`, further-fallback
this session — the pipeline's primary and documented fallback
external reviewers were both offline this session) returned four
PARTIAL verdicts. Two were folded inline (Q2 event-kind structural sync,
Q3 path normalization). Two were logged as v0.6 items (Q1 no fix
needed per reviewer; Q4 partial-cleanup on semantic-init failure).

Branches surfaced against the FINISHED code + reviewer findings:

- **A. Structural-sync class across parallel closed vocabularies.**
  Q2 surfaced the MEMORY_EVENT_KINDS ↔ LEGAL_EVENT_KINDS drift risk;
  the fold added an import-time subset assertion. Broader class:
  every module that maintains a "mirror" set against a shipped
  closed vocabulary is exposed to the same drift. Concrete: the
  `LEGAL_EVENT_KINDS` frozenset auto-recomputes; a manual mirror
  in a sibling module does NOT. **Merge branch** — future closed-
  vocabulary bumps must audit for mirror sets.
- **B. Path-normalization discipline at every string-set membership
  check.** Q3 surfaced separator + prefix drift for
  `_load_manifest_files` / `_diff_touched_files`. Broader class:
  every ALM gate that compares file-path strings across sources
  (LSP-emitted vs git-diff-emitted vs test-manifest-emitted) needs
  the same normalization; `symgraph.py` and `patchdiff.py`
  candidates worth an audit. **Merge branch** — Flagged gap for
  v0.6 sweep.
- **C. Partial-state cleanup on multi-stage init.** Q4 surfaced the
  `ract memory init` semantic-index partial-state class. Broader
  class: multi-stage build verbs (symbol → graph → semantic) need
  a consistent choice — atomically-all-or-none, or clearly-labeled
  partial-success. Today it is partial-success with per-stage
  warnings. **Merge branch** — Flagged gap for v0.6 (idempotent
  atomic init).
- **D. Metadata-channel schema documentation.** The
  `SubstrateStepSpec.metadata: dict` field is the wiring channel
  for module_09 but is untyped. A future era that adds
  `metadata["plan_signature"]`, `metadata["companion_verdict"]`,
  etc. has no discovery surface. **Merge branch** — Flagged gap
  for v0.6 (either promote the metadata channel to a TypedDict or
  document its evolving key set in `docs/EVENTS.md` alongside the
  event schema).
- **E. Legacy-caller preservation as a first-class invariant.**
  PRE Lateral Chain branch C called out G6's legacy fallback; the
  fold shipped enforce_g6 UNCHANGED and added enforce_g6_edit as a
  separate helper. The pattern is: extension by NEW SURFACE, not
  in-place signature mutation. Broader class: v0.6 module_10
  should confirm this pattern holds for every v0.4-legacy surface
  the memory discipline touches. **Merge branch** — inbound
  constraint for module_10 close review.

**Prune:** A, B, C, D, E — all five change how a maintainer will
touch this surface. A is closed by the shipped fold; B/C/D are
inbound to v0.6; E is inbound to module_10.

**Up-intent verify:** sharper. The intent framed module_09 as
"integration wiring"; the SP surfaced two integration-specific
classes (mirror-drift, path-normalization) plus one operational
class (partial-state cleanup) plus one documentation class
(metadata schema). Each branch names a concrete next step.

## Depth Chain pass (POST-audit)

**Load-bearing assumption (from PRE-build).** `SubstrateLoop.run_
step` signature does not change; only the metadata reading changes.
**Confirmed** against landed code:
`src/ract/executor/loop.py::SubstrateStepSpec` gains a `metadata:
dict = field(default_factory=dict)` field (line ~89) — a strictly
additive keyword. Existing v0.4.x callers that construct a spec
without the field see `metadata == {}` and reach the
`_maybe_emit_retrieval_satisfied` early-return at
`src/ract/executor/loop.py::_maybe_emit_retrieval_satisfied` line
~419 (spec.metadata.get returns None → return). Regression:
`tests/contracts/test_auction_wired_into_substrate_loop.py` all
three tests green post-module_09.

**Core dependency.** The Rootknot compatibility reader path is
sacred spine. **Confirmed** by
`tests/memory/test_rootknot_retrieval_attestation.py::test_older_
sidecar_still_verifies` passing green against v1 sidecars, plus
`test_v3_without_field_verifies` green against v3 sidecars without
the attestation field. The `retrieval_attestation is None` branch
in `canonical_bytes()` skips the field entirely
(`src/ract/core/rootknot.py` line ~215), so pre-module_09 v3 knots
produce identical bytes under module_09 code load.

**Depth-4 leaves against delivered facts:**

- **Leaf (a):** Seven kinds land in `EventKind` at
  `src/ract/trace/events.py:89-97`; `LEGAL_EVENT_KINDS` auto-
  recomputes via `typing.get_args(EventKind)` line ~99;
  membership + count-≥32 tests green at
  `tests/memory/test_event_kinds_extended.py`. Second Pass Q2
  fold added `_assert_memory_kinds_subset_of_legal` structural
  check at `src/ract/memory/events.py` line ~65; regression test
  `test_memory_kinds_subset_of_legal_kinds` green.
- **Leaf (b):** `SubstrateStepSpec.metadata` reads produce
  `retrieval.satisfied` events with `total_tokens`,
  `budget_used_pct`, `call_id` populated per the bundle at
  `src/ract/executor/loop.py::_maybe_emit_retrieval_satisfied`
  line ~420-445. Regression:
  `tests/contracts/test_substrate_loop_retrieval_wiring.py::test_
  metadata_bundle_emits_retrieval_satisfied` green with all three
  payload fields asserted; `test_metadata_absent_emits_no_
  retrieval_event` green for the fall-through path.
- **Leaf (c):** `enforce_g6_edit(diff, plan)` refuses on files
  outside `plan.load_manifest` at
  `src/ract/antilazy/pre_commit.py::enforce_g6_edit` line ~490;
  `enforce_g7_edit(diff, companion)` refuses on companion's
  False verdict at line ~530. Second Pass Q3 fold added
  `_normalize_file_path` at line ~570; regression tests
  `test_backslash_vs_forward_slash_normalized` +
  `test_leading_dot_slash_normalized` green.
- **Leaf (d):** Three new CLI verbs resolve through argparse
  --help at
  `tests/memory/test_cli_memory_verbs.py::test_help_resolves`
  (three parametrized cases green); the smoke
  `test_memory_init_smoke` builds a symbol index at a tmp path
  and asserts the .db file exists post-run.

**Up-chain verify:** each leaf serves the parent Intent as
delivered. The intent framed integration wiring across
SubstrateLoop + events + Rootknot + ALM + CLI; leaves (a)-(d)
land one delivered fact per surface and the SP verdicts (post-
fold) confirm each surface preserves its documented contract.

**Inbound constraints for module_10 (release close):**

1. **Golden hash re-lock.** Module_09 landed the hash at
   `2905a2b789aa9900398de7ce6924d32919dd532618a835c118841c8c3826b8b0`
   (fixed-point iter 0 post-SP-fold + ruff format pass). Module_10
   re-locks against any release-close file touches (CHANGELOG,
   README, ROADMAP, VERSION triple).
2. **`docs/ROADMAP.md` compilation.** Six v0.6-hardening items
   surfaced across module_09 that must land in ROADMAP under the
   v0.6 section: (a) SP Q1 canonical-bytes ordering audit under
   Python < 3.11 (informative — reviewer said no fix needed;
   document the deterministic-sort claim); (b) SP Q3 path-
   normalization sweep across `symgraph.py` + `patchdiff.py`;
   (c) SP Q4 atomic-init for `ract memory init` semantic stage;
   (d) three-index wiring for `ract retrieval query` (today only
   returns a canonical-query projection); (e) provider-bridge
   from `MemoryFunctionProvider` → `ProviderAdapter.complete`;
   (f) SUMMARY provider adapter (carried forward from module_05
   POST + module_06 POST + module_07 POST).
3. **Handshake-gated push.** Module_10 push is gated per invariant
   five; the annotated tag body must be closed-IP-scan clean. The
   pre-existing `_BUILD/**` closed-IP hits (four inherited term
   families in the module_06-08 status log) inherited from
   module_06 close are NOT introduced by module_09; the tag body
   scan runs against tracked files at HEAD, which includes those
   files — module_10 must either narrow the wordlist scan
   exclusion or generalize the leaking text before the annotated
   tag lands.
4. **Legacy-caller preservation invariant.** Post-audit branch E:
   module_10 should confirm that every v0.5.0 module extended a
   v0.4-legacy surface by NEW SURFACE rather than in-place
   mutation. Concrete: enforce_g6 UNCHANGED + enforce_g6_edit
   ADDED; SubstrateStepSpec metadata ADDED as opt-in keyword.
5. **Metadata channel documentation.** POST branch D: module_10
   should decide whether `SubstrateStepSpec.metadata` graduates
   to a TypedDict or remains a free-form dict with an evolving
   key set documented in `docs/EVENTS.md`.
6. **Full-suite regression at the tag commit.** Module_09 close
   ran `tests/memory/` (452 passed / 2 skipped) + gate suite
   (source-digest, dead-code-auction, public-provenance,
   test-substrate-loop, test-antilazy-g5-g6 all green). The
   pre-existing closed-IP scan failure inherited from module_06
   is NOT introduced here; module_10 close inherits the same
   condition and MUST fold or document it before tag.

## Definition of Done

- `src/ract/trace/events.py::EventKind` includes the seven new
  kinds; `LEGAL_EVENT_KINDS` auto-recomputes.
- `src/ract/executor/loop.py::SubstrateLoop.run_step` reads
  `SubstrateStepSpec.metadata["retrieval_bundle"]` when present.
- `src/ract/core/rootknot.py` generator payload carries optional
  `retrieval_attestation`; compatibility reader path intact.
- `src/ract/antilazy/pre_commit.py::enforce_g6` and `enforce_g7`
  accept `CandidateDiff | None`.
- `src/ract/cli.py::CLI_VERBS` extended with `memory`; three new
  subverbs (`init`, `apply-narrowings`, `query` under `retrieval`).
- Sacred-spine test `test_older_sidecar_still_verifies` green
  against v1, v2, v3-without-attestation fixtures.
- `pytest -q tests/executor/test_substrate_loop_retrieval_wiring.py
  tests/memory/test_rootknot_retrieval_attestation.py
  tests/memory/test_g6_edit_under_edit_closure.py
  tests/memory/test_g7_edit_companion_review.py
  tests/memory/test_cli_memory_verbs.py
  tests/memory/test_event_kinds_extended.py` all green.
- `ruff check src/`, `mypy src/ract`, and full `pytest -q` all
  clean.
- ADR-0039 exists; `docs/EVENTS.md` schema-version bumped;
  `docs/ARCHITECTURE.md` SubstrateLoop section updated.
- Closed-IP wordlist scan: zero hits.
- Second Pass complete.

## Reference sources

- MEMORY DISCIPLINE spec §Integration surface with existing RACT,
  §Sacred spine, §Signals items 11-13.
- `src/ract/executor/loop.py` and
  `_BUILD/ract_v0.4.0_substrate/module_02.md` for the SubstrateLoop
  precedent.
- `src/ract/core/rootknot.py` and
  `_BUILD/ract_v0.4.0_substrate/module_06.md` for the compatibility
  reader path.
- `src/ract/antilazy/pre_commit.py` and
  `_BUILD/ract_v0.4.0_antilazy/module_02.md`,
  `_BUILD/ract_v0.4.0_antilazy/module_04.md` for the ALM gate
  precedents.
- `src/ract/cli.py` and
  `_BUILD/ract_v0.5.0_intent_fidelity/module_01.md` for the CLI
  verb pattern.

## Flagged gaps (to log at close)

Six items surfaced by Second Pass + PRE Lateral Chain that defer
to v0.6 hardening. Each names a concrete owner-shape decision.

1. **SP Q1: Rootknot canonical-bytes ordering audit.** Reviewer
   said no fix needed — the `sort_keys=True` on `json.dumps`
   is deterministic across Python versions for ASCII keys. Log
   as informative; a paranoid v0.6 sweep might add a golden-
   canonical-bytes fixture that pins a v3-with-attestation knot's
   bytes across Python 3.11 / 3.12 / 3.13 runs.
2. **SP Q3 broader: path-normalization sweep.** Q3 fold added
   `_normalize_file_path` at `enforce_g6_edit`. The same class
   applies to `symgraph.py`'s edited_symbols path comparison and
   `patchdiff.py`'s leakage-match path comparison. v0.6 audit
   should confirm each site normalizes identically.
3. **SP Q4: atomic init for `ract memory init` semantic stage.**
   Today a mid-build semantic failure leaves an empty
   `semantic_dir/`. v0.6: either build in a temp dir and move on
   success, or add a `--rebuild` flag that clears the target dir
   before starting.
4. **Three-index wiring for `ract retrieval query`.** Today the
   verb returns only a canonical projection of the query. Full
   wiring against a live `retrieve()` pipeline (three indexes +
   cache + query-trace) needs the composition_runner surface to
   accept a bare query. v0.6.
5. **Provider bridge `MemoryFunctionProvider` →
   `ProviderAdapter.complete`.** Carried forward from module_06
   POST inbound constraint. The bridge is a thin adapter around
   the two Protocol surfaces; not shipped in module_09 because
   the CLI paths do not invoke a live model call today.
6. **SUMMARY provider adapter.** Carried forward from module_05
   POST + module_06 POST + module_07 POST inbound constraints.
   Same rationale as #5 — no CLI or SubstrateLoop path invokes
   the SUMMARY format today.

Beyond the six, the operator's inbound-constraint list surfaced
19+ additional items across modules 01-08 POSTs. Judgment call:
the DoD-critical wiring (SubstrateLoop metadata, event kinds,
Rootknot extension, ALM edit-path helpers, three CLI verbs) all
landed and passed gates. The larger integration items (FTS5
write-cost budgeting, three-consumer TokenEstimator fan-out,
verify_prompt_coverage at startup, probe_lancedb at startup,
current_budgets from probes, fingerprint-mapper wiring,
PhaseRecord token counts, wall-clock-guard interactive
update_file, traversal-id cap wide fan-out, watcher-glob
exclusion for probe fixtures, LSP language-per-suffix dispatch,
composition_runner as `ract run` verb, ambiguity halt path,
playbook budget overrides, plan.mid_invocation_queries wiring,
live_current_value pass-through, unwire-3-basename dead-code
allowlist, `accountant.record_narrowing` before `emit_budget_
declared`, tmp-file cleanup on SIGKILL) all defer to v0.6 as
integration polish. Module_09 shipped the shape; module_10
(release close) inventories what the shape landed vs what a
v0.6 pass would tighten.
