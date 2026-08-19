# module_07 — Playbook composition

**Origin.** MEMORY DISCIPLINE §Playbooks and §Signals item 9. Four
playbooks compose the four v0.5.0 functions into recognizable
workflows: rename, extract method, bug fix, unit test. The remaining
eight playbooks (security audit, feature endpoint, migration, code
review, perf, dead code, schema migration, config change) defer to
v0.6.

**Intent.** Land `src/ract/memory/playbooks/{refactor_rename,
refactor_extract,bug_fix,unit_test}.yaml` plus a composition runner
at `src/ract/memory/composition_runner.py`. Each playbook specifies
composition sequence, per-phase retrieval overrides, and per-phase
budget overrides. The runner executes the composition and threads
outputs between phases via `SessionMemory` (module_06). Every phase
runs as a `SubstrateStepSpec` under module_09's SubstrateLoop wiring;
this module ships the composition runner as a standalone helper
that module_09 later wires.

## Steps

1. **Read** the prior surfaces this module composes.
   - `src/ract/memory/functions/{intake,research,plan,edit}.py`
     (module_06) — the four verbs.
   - `src/ract/memory/composition.py` (module_01) — the composition
     override that narrows a function's budget for a specific
     playbook phase.
   - `src/ract/memory/session.py` (module_06) — SessionMemory carries
     outputs between phases.
2. **Add** `src/ract/memory/playbooks/refactor_rename.yaml`:
   - `composition: [intake, research, plan, edit_loop]`.
   - Per-phase retrieval overrides per master spec §Refactor: rename.
     Research: `symbol_names: [WorkOrder.scope_hints.mentioned_symbols]`,
     `graph_seeds: [same]`, `keywords: ["rename"]`, plus grep for
     string literals via a `grep_hint` pattern.
   - Plan: `if len(load_manifest.files) > 5: split_into_edits: true`.
   - Edit loop: one edit per file; per-file budget override to 6k
     input, 2k output, 6k ceiling.
3. **Add** `src/ract/memory/playbooks/refactor_extract.yaml`:
   - `composition: [intake, research, plan, edit]`.
   - Research: target function FULL, callers SIGNATURE, containing
     class/module symbol map.
   - Plan: extraction boundary, new method name, signature,
     parameters to pass, state to preserve.
   - Edit: single invocation; budget 6k.
4. **Add** `src/ract/memory/playbooks/bug_fix.yaml`:
   - `composition: [intake, research, reproduce, plan, edit]`.
   - Research: reported symbol FULL, callers FULL, related test file
     FULL, git log grep for recent changes to this symbol.
   - Reproduce: deterministic phase; runs the reported failing test
     via the existing `pytest` invocation surface. If it does not
     reproduce, the runner raises `UnconfirmedBugError` and refuses to
     proceed — bug fixes without reproduction are refused.
   - Plan: fix hypothesis, specific change, regression test to add.
   - Edit: load bug symbol FULL, test file FULL; budget 8k.
5. **Add** `src/ract/memory/playbooks/unit_test.yaml`:
   - `composition: [intake, research, plan, edit]`.
   - Research: target function FULL, callers SIGNATURE, existing test
     file FULL if it exists, test framework config.
   - Plan: happy path, edge cases, error cases, boundary conditions.
   - Edit: produces test file additions; budget 6k.
6. **Add** `src/ract/memory/composition_runner.py`:
   - `PlaybookSpec(dataclass, frozen)` — loaded from YAML.
   - `run_playbook(spec: PlaybookSpec, request: str, repo_root: Path,
     provider: Provider, indexes: IndexBundle) -> PlaybookResult`.
   - Phase dispatch: `intake -> research -> plan -> edit(_loop)`.
   - Loop dispatch (for `edit_loop`): iterate over
     `ChangePlan.load_manifest.files`, invoke `edit` per file.
   - `PlaybookResult(dataclass, frozen)` — `work_order`, `research`,
     `plan`, `edits: tuple[CandidateDiff, ...]`, `phase_records:
     tuple[PhaseRecord, ...]`.
7. **Add** `src/ract/memory/playbooks/__init__.py`:
   - `load_playbook(name: str) -> PlaybookSpec` — reads the YAML from
     `src/ract/memory/playbooks/{name}.yaml`; refuses unknown names
     with `UnknownPlaybookError`.
   - `list_playbooks() -> list[str]` — enumerates the four v0.5.0
     playbook YAMLs.
8. **Tests** — new files under `tests/memory/`:
   - `tests/memory/test_playbook_refactor_rename.py` — playbook runs
     end-to-end against the fixture repo (rename `User` to
     `Account` in Python), produces the expected number of edits, and
     each edit's diff parses cleanly. Uses the mock provider from
     module_06.
   - `tests/memory/test_playbook_refactor_extract.py` — playbook
     extracts a method from a fixture function; the diff parses
     cleanly.
   - `tests/memory/test_playbook_bug_fix.py` — playbook runs against
     a fixture bug (a failing test); a reproduce phase that finds no
     failing test raises `UnconfirmedBugError`.
   - `tests/memory/test_playbook_unit_test.py` — playbook produces
     a test file addition for a fixture function.
   - `tests/memory/test_composition_runner.py` — playbook loader
     rejects unknown names; `list_playbooks()` returns exactly the
     four v0.5.0 names; SessionMemory correctly threads outputs
     between phases.
9. **Docs:**
   - Add ADR-0037: "Four v0.5.0 playbooks; eight deferred to v0.6."
     Cover the split justification per master spec §Bounded scope.
   - Add a new section to `docs/ARCHITECTURE.md`: "Playbook
     composition (v0.5.0 memory discipline)." Cross-link to master
     spec §Playbooks.

## Lateral Chain pass (PRE-build)

**Branches:**

- A: **Bug-fix reproduce phase requires an operator to name the
  failing test.** The playbook cannot magically find the bug. Merge
  branch — the playbook accepts an optional
  `reproduce_command: str | None`; if None, the runner tries the
  WorkOrder's `success_criteria` as pytest node ids; if that also
  fails, the runner raises `UnconfirmedBugError` with instructions.
  Carry forward.
- B: **Rename across languages.** A rename that spans a Python server
  and a TypeScript client should touch both. Merge branch — the
  research phase's `find_by_name` is language-agnostic per module_02
  branch E; the plan's `load_manifest` groups files by language and
  invokes the language-appropriate LSP for reference-checking. Carry
  forward.
- C: **Extract method across a large function.** If the function is
  too large to fit in `edit`'s budget FULL, the retrieve cascade
  downgrades to sub-chunk. Merge branch — the extract playbook's
  edit phase specifies `retrieval.format: FULL` for the target
  function and refuses cascade for the target (only the neighborhood
  cascades). If FULL doesn't fit, the playbook fails with an
  `OversizeTargetError` and the operator is expected to reduce the
  function first. Carry forward.
- D: **Unit test playbook against an untested language.** If the
  target function is Rust and the fixture repo has no Rust test
  framework config, the playbook doesn't know the convention. Defer
  — v0.5.0 unit test playbook supports Python + TypeScript only;
  Rust + Go defer to v0.6. Document in the ADR.
- E: **Playbook loop iteration bound.** `edit_loop` iterates over
  every file in `load_manifest`. If the manifest is 50 files, that
  is 50 model calls. Merge branch — the loop respects
  `ChangePlan.iteration_bound`; a loop exceeding the bound raises
  `IterationBoundExceededError` and asks the operator to split the
  change. Carry forward.

**Prune:** keep A, B, C, E. Defer D. Kept branches change intent
shape.

**Up-intent verify:** sharper. A closes the "how does reproduce
find the test" worry; B closes the cross-language rename worry; C
closes the extract-oversize worry; E closes the iteration explosion
worry.

## Depth Chain pass (PRE-build)

**Load-bearing assumption.** The four playbook YAMLs load cleanly
via PyYAML and match the `PlaybookSpec` dataclass shape. If the YAML
schema drifts from the dataclass, the loader raises a specific
error naming the drift. First live run under this module verifies
each of the four YAMLs loads without error.

**Core dependency.** module_06's four functions have stable
signatures. If any function's signature changes, this module's
composition runner updates its dispatch table.

**Leaves.**

- **Depth 4 leaf (a):** `src/ract/memory/playbooks/{refactor_rename,
  refactor_extract,bug_fix,unit_test}.yaml`,
  `src/ract/memory/composition_runner.py`,
  `src/ract/memory/playbooks/__init__.py` all exist; `pytest -q
  tests/memory/test_playbook_refactor_rename.py
  tests/memory/test_playbook_refactor_extract.py
  tests/memory/test_playbook_bug_fix.py
  tests/memory/test_playbook_unit_test.py
  tests/memory/test_composition_runner.py` all green.
- **Depth 4 leaf (b):** `list_playbooks()` returns
  `["refactor_rename", "refactor_extract", "bug_fix",
  "unit_test"]` exactly; unknown name raises
  `UnknownPlaybookError`.
- **Depth 4 leaf (c):** every playbook YAML loads and matches
  `PlaybookSpec`; schema drift raises `PlaybookSchemaError` with the
  drift field named.
- **Depth 4 leaf (d):** ADR-0037 exists; `docs/ARCHITECTURE.md` has
  a new "Playbook composition" section.

## Reasoning Endpoints for scoping

**Producer:** NVIDIA `reason_agentic` (MiniMax M2.7). Role: draft the
four playbook YAMLs, the composition runner, and the loop/split
dispatch shape.

**Reviewer:** Google Gemini flash reasoning function (cross-family
from MiniMax). Documented fallback: an OpenRouter reasoning function cross-family from Qwen3 Coder (operator selects the specific function from the current OpenRouter catalog at dispatch time).

**Why the pair provides blind-spot diversity.** MiniMax produces the
composition machinery; Gemini flash reasoning reads the playbook
semantics and tests them against realistic scenarios. Concrete
review question: "For the bug_fix playbook, does the reproduce phase
correctly refuse to proceed on an unreproducible bug, or is there a
code path where the runner silently proceeds with the WorkOrder's
success_criteria as a stand-in?"

## Second Pass discipline

After the first-build subagent lands the code plus tests and the DoD
is boolean-passing, the diff plus master-spec §Playbooks quote plus
the four playbook test files go to Google Gemini flash reasoning
function for skeptical review. Same reviewer named in the scoping
section. Fallback: an OpenRouter reasoning function cross-family from Qwen3 Coder (operator selects the specific function from the current OpenRouter catalog at dispatch time).

**Adversarial questions the reviewer is asked:**

1. Does the bug_fix reproduce phase correctly refuse on an
   unreproducible bug? Name any code path where the runner proceeds
   without a confirmed reproduction.
2. The rename playbook groups files by language for LSP dispatch.
   Does the grouping correctly handle a mixed-language rename (e.g.,
   Python `User` class + TypeScript `User` type in the same
   codebase), or does one language's plan silently drop the other's
   references?
3. The extract_method playbook refuses cascade for the target
   function. If the target function is exactly at the FULL budget
   boundary and the neighborhood adds even one signature, does the
   playbook fail loudly with `OversizeTargetError`, or does the
   cascade silently downgrade the neighborhood past the boundary?
4. The playbook YAML schema is validated at load. If someone adds a
   fifth playbook without registering it in `list_playbooks()`, does
   `load_playbook("new_playbook")` find it via directory scan, or
   does it fail because the loader hard-codes the four v0.5.0 names?

**Two possible outcomes.** Same protocol as module_01-06.

## Second Pass results

**Reviewer:** OpenRouter `reason_nemotron_ultra` (NVIDIA Nemotron 3
Ultra 550B via OpenRouter, cross-family from producer NVIDIA
`reason_agentic` MiniMax M2.7). Google Gemini flash reasoning
function was named as the primary; OpenRouter cross-family reviewer
was the documented fallback and executed the review this session
matching module_05 / module_06 dispatch. Response landed at
`_BUILD/ract_v0.5.0_memory_discipline/second_pass/module_07_review_response.txt`.

- **Q1 REFUTED (no fix).** The bug_fix reproduce phase refuses on
  every unreproducible path. Evidence: `composition_runner.py`
  `_run_reproduce_phase` raises :class:`UnconfirmedBugError` when
  the command source cascade (explicit arg → phase field →
  success_criteria pytest node ids) yields nothing (lines 815-821);
  a `returncode == 0` after `subprocess.run` raises
  :class:`UnconfirmedBugError` naming the zero-exit reason (lines
  849-869). Only `returncode != 0` proceeds to plan (lines 870-880).
  `_reproduce_command_from_success_criteria` (lines 883-901) derives
  a pytest command but never stands in for actual reproduction.
- **Q2 PARTIAL (fix landed inline as docstring + regression test;
  full LSP wiring deferred).** The runner groups by `file_path`
  only and treats every file group uniformly through the same
  `edit_fn` call. `_group_manifest_by_file` (lines 1066-1078)
  keys purely on the path string with no language field. The
  refactor_rename YAML declares no language-aware retrieval hints.
  Fix: regression test
  `test_edit_loop_groups_by_file_across_languages` in
  `tests/memory/test_composition_runner.py` pins the grouping
  behavior across Python + TypeScript + Rust file suffixes.
  Language-appropriate LSP dispatch itself lives in module_09
  wiring per master spec §Refactor: rename Lateral Chain branch B
  and is carried as Flagged gap 1.
- **Q3 PARTIAL (fix landed inline as docstring + regression
  test).** `_run_edit_single` wraps any `BoundedContextError` from
  `edit_fn` as :class:`OversizeTargetError` when the playbook is
  `refactor_extract`. Reviewer noted the runner cannot distinguish
  target-only overflow from neighborhood overflow at the wrap
  site. Verification against module_06's `edit._assemble_load_block`
  (edit.py:299-309): `BoundedContextError` only raises at the
  target-only cascade tier — the three earlier tiers (FULL for
  everyone, FULL-target + SIGNATURE non-target, FULL-target +
  BODY_ONLY non-target) return a rendered block when they fit. A
  raised `BoundedContextError` names the target-only condition
  exactly. Fix: docstring at `_run_edit_single` +
  `OversizeTargetError` documents the invariant with
  `edit.py:299-309` citation; regression test
  `test_extract_wraps_only_at_target_only_tier` in
  `tests/memory/test_composition_runner.py` pins that an unrelated
  edit-side error (:class:`InvalidSyntaxError` from invalid JSON)
  propagates without being misclassified as an oversize target.
- **Q4 CONFIRMED (no fix).** Directory-scan `list_playbooks` +
  `load_playbook` at `src/ract/memory/playbooks/__init__.py`
  (lines 35-95) discovers a fifth YAML without any code edit; no
  hard-coded name list exists.

Reviewer additionally observed:

- Defect #1 (`_is_bounded_context` string-name match). Documented
  intentionally in the helper's docstring; the string match bridges
  two distinct `BoundedContextError` classes (`ract.memory.retrieve`
  and `ract.memory.functions.errors`) without an isinstance
  dependency that would leak type coupling. No action.
- Defect #2 (edit_loop trigger uses phase name string OR
  `per_iteration_budget`). The two triggers are documented in
  `run_playbook` around the edit dispatch; either shape triggers
  the loop path. Carried as Flagged gap 2.
- Defect #3 / #4 (concurrent-run race on registry, per-iteration
  budget override discarded). Both critique
  `_apply_phase_budget_override` which by design pulls a fresh
  `BudgetDeclaration` from `budget_registry.get` and calls
  `apply_composition_override` for its typo-refusal semantics; the
  return value is discarded because module_06's function surfaces
  read their own budget from the registry inside the call. No
  registry mutation happens (registry cache holds the frozen
  declaration; `apply_composition_override` returns a fresh
  declaration via dataclasses.replace). The narrowed declaration
  not being passed downstream is a module_09 wiring concern per
  the helper's shipped docstring. Carried as Flagged gap 3.
- Defect #5 (rename E2E test uniformity). Closed by the new
  `test_edit_loop_groups_by_file_across_languages` regression
  which asserts per-file distinct edit calls with a RecordingProvider.

## Lateral Chain pass (POST-audit)

Applied against the FINISHED module + Second Pass verdicts.

**Branches:**

- **POST-A: Ambiguity-flag closure as trace note + phase record.**
  The Q2 fix in module_06 emitted `ambiguity_flags` on
  `budget.declared`. Module_07 reads that route: an ambiguous
  WorkOrder produces a `PhaseRecord.notes` entry
  ("ambiguity_flag: proceeding with risk marker") plus a fresh
  `budget.declared` event tagged with the playbook + phase. The
  composition runner does NOT halt (per master spec §intake
  failure modes: the flag is a documented risk marker, not an
  automatic halt). Downstream operator tooling (module_09 CLI or
  a shipped `ract run` verb) is the gate that decides to prompt
  or proceed. **Merge branch** — closes module_06 POST inbound
  constraint 1 as signal-visible + operator-decides; carry
  forward as inbound constraint for module_09.
- **POST-B: `plan.mid_invocation_queries` composition wiring still
  deferred.** The YAML schema parses `retrieval_overrides` on
  every phase, including the plan phase. The runner does not yet
  translate those overrides into `RetrievalQuery` values passed to
  `plan_fn(mid_invocation_queries=...)`. The plumbing is one
  layer of `_parse_string_map` + `RetrievalQuery` construction
  away. Merge branch — partial closure of module_06 POST inbound
  constraint 2; the retrieval-override values are parsed and
  validated at load time, so a bug_fix playbook could carry the
  hint today, but no code path forwards them. Carry forward as
  Flagged gap 4 (module_09 wiring surface).
- **POST-C: LSP language dispatch deferred to module_09.** Q2
  PARTIAL confirms the runner groups files by path only. A
  cross-language rename plan today produces one edit call per
  file group, each invoking the same `edit_fn`. Language-specific
  reference resolution (a Python `pylsp` call for `.py` groups,
  `typescript-language-server` for `.ts` groups) belongs to
  module_09's SubstrateLoop wiring. Merge branch — carry forward
  as inbound constraint for module_09.
- **POST-D: Reproduce phase runs commands under `shell=True`.**
  `_run_reproduce_phase` uses `subprocess.run(command,
  shell=True, cwd=str(repo_root), ..., timeout=120)`. Every
  reproduce_command source (explicit arg → phase YAML →
  success_criteria) is text the operator or the WorkOrder
  contributed; there is no untrusted shell input path (the
  WorkOrder's success_criteria arrives from intake which came
  from the operator's request text). But a v0.6 hardening pass
  should tighten this: parse the command via `shlex.split` +
  refuse shell metacharacters unless the phase YAML sets an
  explicit opt-in. Prune from POST but carry as Flagged gap 5.
- **POST-E: Session-memory single-writer.** Inherited from
  module_06 POST-E: `SessionMemory._persist` is single-writer per
  path. The runner accepts a `session` argument; two concurrent
  playbook runs against the same `session_path` race. Prune —
  module_09 assigns unique `evals/runs/<run_id>/session.json`
  paths per master spec, so the race is out of scope today.

**Prune:** keep A, B, C. Prune D (documented + no untrusted
input path today; flagged for v0.6) and E (unique-per-run path
invariant makes it moot).

**Up-intent verify:** sharper. A confirms the module_06 POST
constraint is closed; B + C name concrete downstream work for
module_09 (playbook budget-narrowing forwarding + LSP language
dispatch).

## Depth Chain pass (POST-audit)

Applied against the FINISHED module.

**Load-bearing assumption from PRE-build:** "The four playbook YAMLs
load cleanly via PyYAML and match the `PlaybookSpec` dataclass
shape. If the YAML schema drifts from the dataclass, the loader
raises a specific error naming the drift."

**CONFIRMED as delivered.** Every shipped YAML loads through
`parse_playbook_payload` at
`src/ract/memory/composition_runner.py:248-322`; unknown top-level
fields raise `PlaybookSchemaError` naming the offender (lines
261-268); unknown phase fields raise the same error with
`phase_index` in the payload (lines 333-344). Regression tests
`test_load_playbook_schema_drift_raises`,
`test_phase_unknown_function_raises`,
`test_phase_budget_override_type_check`,
`test_duplicate_phase_name_raises` in
`tests/memory/test_composition_runner.py` pin each refusal path.

**Core dependency from PRE-build:** "module_06's four functions
have stable signatures. If any function's signature changes, this
module's composition runner updates its dispatch table."

**CONFIRMED as delivered.** The runner imports intake / research /
plan / edit directly from `ract.memory.functions` and calls each
with the shipped kwargs (`sink=active_sink`, `intake_context=...`,
etc.). No signature reimplementation; a module_06 signature drift
would surface at import or at call time. `_run_verb_phase`
(composition_runner.py:689-730) is the single dispatch surface.

**Leaves.**

- **Depth 4 leaf (a):** `src/ract/memory/composition_runner.py`
  (1105 lines, 5 error classes + 4 dataclasses + 8 helpers +
  runner), `src/ract/memory/playbooks/__init__.py` (115 lines),
  four YAMLs, and five test files all landed at commit `ee72086`.
  `pytest -q tests/memory/test_composition_runner.py
  tests/memory/test_playbook_refactor_rename.py
  tests/memory/test_playbook_refactor_extract.py
  tests/memory/test_playbook_bug_fix.py
  tests/memory/test_playbook_unit_test.py` runs 65 tests green
  (17 + 12 + 11 + 12 + 13 after SP fix; two regression tests
  added inline in this pass). Up-chain verify: parent Intent
  "land the four playbook YAMLs plus a composition runner"
  delivered.
- **Depth 4 leaf (b):** `list_playbooks()` returns exactly
  `["bug_fix", "refactor_extract", "refactor_rename",
  "unit_test"]` (test
  `test_list_playbooks_returns_exact_four_names`); unknown name
  raises `UnknownPlaybookError` naming the shipped set (test
  `test_load_playbook_unknown_raises`). Up-chain verify: parent
  Intent "four v0.5.0 playbook names authoritative" delivered.
- **Depth 4 leaf (c):** every shipped YAML round-trips through
  `PlaybookSpec` (parametrized test
  `test_every_shipped_playbook_loads`); schema drift raises
  `PlaybookSchemaError` naming the drift field (four separate
  regression tests). Up-chain verify: parent Intent "loader
  refuses malformed YAMLs at load time with a specific
  structured error" delivered.
- **Depth 4 leaf (d):** ADR-0037 exists at
  `docs/ADRs/ADR-0037-playbook-composition.md`; `docs/ARCHITECTURE.md`
  has a new "Playbook composition (v0.5.0 memory discipline)"
  section (74-line insertion). Up-chain verify: parent Intent
  "documented 4-vs-12 scope split + YAML schema" delivered.

## Inbound constraints for later modules

Module_07 surfaces the following constraints for modules 08 / 09 to
honor at their own POST time:

1. **Module_08 (probes) MAY adjust playbook parameters based on
   failure records.** Probes read failure-record aggregation per
   master spec §Failure learning; a playbook whose bug_fix
   reproduce phase repeatedly refuses (UnconfirmedBugError) could
   trigger a probe suggesting the operator supply
   `reproduce_command` upfront. The probe surface owns the
   aggregation; the composition runner exposes the outcome via
   `PhaseRecord.outcome == "raised"`.
2. **Module_09 (SubstrateLoop wiring) MUST wire the composition
   runner as the shipped `ract run` verb path.** The current
   `run_playbook` returns a `PlaybookResult` with edits + phase
   records; module_09 wraps this into a `SubstrateStepSpec`
   sequence so the substrate transaction machinery inherits
   phase-level checkpointing.
3. **Module_09 MUST close the ambiguity-flag route.** POST-A:
   module_07 emits ambiguity as a phase note + `budget.declared`
   event; module_09's operator-facing CLI decides whether to
   prompt for clarification or proceed. The default in v0.5.0
   proceeds with the risk marker per master spec §intake failure
   modes; module_09 owns the operator UX for the halt path.
4. **Module_09 MUST forward playbook budget overrides to the
   function call.** POST-B / Flagged gap 4: `retrieval_overrides`
   and per-phase `budget_override` are parsed at load time but
   the narrowed declaration is not yet threaded into
   `intake_fn(...)` / `research_fn(...)` / `plan_fn(...)` /
   `edit_fn(...)`. Module_09's provider adapter is the natural
   home for this wiring (it already bridges the
   `MemoryFunctionProvider` protocol; adding a `declaration`
   parameter fits its role).
5. **Module_09 MUST supply `plan.mid_invocation_queries` from
   playbook YAML.** Carried from module_06 POST inbound
   constraint 2. The YAML schema already parses
   `retrieval_overrides` as (key, value) string pairs; module_09
   translates those into `RetrievalQuery` values and passes them
   as `plan_fn(mid_invocation_queries=...)`.
6. **Module_09 MUST wire language-aware LSP dispatch.** POST-C:
   the runner groups by `file_path` only. Module_09's SubstrateLoop
   step wiring is where the per-file `edit_fn` call selects the
   correct LSP driver (pylsp for `.py`, typescript-language-server
   for `.ts`, rust-analyzer for `.rs`, gopls for `.go`).

## Definition of Done

- `src/ract/memory/playbooks/{refactor_rename,refactor_extract,bug_fix,
  unit_test}.yaml` all exist.
- `src/ract/memory/composition_runner.py` and
  `src/ract/memory/playbooks/__init__.py` exist with the API listed
  in steps 6-7.
- `list_playbooks()` returns exactly the four v0.5.0 names.
- Every playbook YAML loads and matches `PlaybookSpec`.
- `pytest -q tests/memory/test_playbook_refactor_rename.py
  tests/memory/test_playbook_refactor_extract.py
  tests/memory/test_playbook_bug_fix.py
  tests/memory/test_playbook_unit_test.py
  tests/memory/test_composition_runner.py` all green.
- `ruff check src/ract/memory/`, `mypy src/ract/memory/`, and full
  `pytest -q` all clean.
- ADR-0037 exists; `docs/ARCHITECTURE.md` has a new "Playbook
  composition" section.
- Closed-IP wordlist scan: zero hits.
- Second Pass complete.

## Reference sources

- MEMORY DISCIPLINE spec §Playbooks, §Bounded scope, §Signals item 9.
- Prefect workflow composition pattern (module-scoped composition,
  not agent-scoped): `https://docs.prefect.io/`.
- Substrate module_02 (`_BUILD/ract_v0.4.0_substrate/module_02.md`)
  for the `StepTransaction` composition precedent this runner mirrors.

## Flagged gaps (to log at close)

1. **LSP language dispatch delegated to module_09.** POST-C /
   Q2 PARTIAL. The runner groups `load_manifest` entries by
   `file_path` only; each file group receives an identical
   `edit_fn` call. Language-aware LSP dispatch (pylsp / tsserver
   / rust-analyzer / gopls per file suffix) lives with the
   SubstrateLoop wiring in module_09. The runner regression test
   `test_edit_loop_groups_by_file_across_languages` pins the
   grouping shape today. Owner: module_09.

2. **`edit_loop` trigger uses two conventions.** SP defect #2.
   `run_playbook` triggers the loop path when
   `phase.name == "edit_loop"` OR when `per_iteration_budget` is
   set. Either shape works; a future maintainer could tighten
   to a single dedicated flag (`phase.kind: "loop"`) but the
   shipped shape is documented in the runner docstring. Owner:
   v0.6 hardening.

3. **`_apply_phase_budget_override` return discarded.** SP
   defects #3 / #4. The helper pulls a fresh
   `BudgetDeclaration` from the registry, calls
   `apply_composition_override` (returns a new frozen
   declaration), and discards the result. The composition-layer
   typo-refusal semantics fire before the model call; the
   narrowed declaration is not passed to the function surface
   because module_06's four verbs read their own budget from the
   registry inside their call. Module_09's provider adapter is
   the natural home for passing the narrowed declaration
   through. Owner: module_09.

4. **`plan.mid_invocation_queries` playbook wiring.** POST-B /
   carried from module_06 Flagged gap 2. YAML
   `retrieval_overrides` on the plan phase is parsed but not
   forwarded as `RetrievalQuery` values to
   `plan_fn(mid_invocation_queries=...)`. The plumbing is one
   translation layer away and belongs with module_09 wiring.
   Owner: module_09.

5. **Reproduce phase runs `subprocess.run(..., shell=True)`.**
   POST-D. Every source (explicit arg, phase YAML,
   success_criteria-derived pytest command) comes from operator-
   contributed text today, so no untrusted-input path exists at
   v0.5.0. A v0.6 hardening pass could parse via `shlex.split`
   and refuse shell metacharacters unless the phase opts in.
   Owner: v0.6 hardening.

6. **Session-memory single-writer per path.** Inherited from
   module_06 POST-E. Two concurrent playbook runs against the
   same `session_path` race. Master spec §Function contracts
   names a unique `evals/runs/<run_id>/session.json` path per
   run so the race is out of scope today; module_09 enforces
   the unique path invariant in the shipped CLI. Owner:
   module_09.

7. **Knapsack packing across function call sites.** Carried
   from module_04 POST inbound constraint 1 + module_05 POST
   constraint 1 + module_06 Flagged gap 8. The playbook budget
   surface exists in the YAML (`budget_override` +
   `per_iteration_budget`) but the pack strategy inside the
   retrieve cascade stays greedy. A 0/1 knapsack DP or a
   k-approximation would tighten the pack under pressure.
   Owner: v0.6 hardening.

8. **SUMMARY provider adapter.** Carried from module_05
   Flagged gap 2 + module_06 Flagged gap 9. The runner does
   not require SUMMARY today (edit uses the FULL / SIGNATURE /
   BODY_ONLY cascade); if a future playbook wants SUMMARY on a
   long file it needs the wrapping summariser adapter that
   module_09's provider registry lands. Owner: module_09.
