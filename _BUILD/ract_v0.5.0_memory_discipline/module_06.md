# module_06 — Function contracts (intake / research / plan / edit)

**Origin.** MEMORY DISCIPLINE §Function contracts and §Signals item 8.
Four verbs carry a change from user request through to a candidate diff.
The remaining four verbs (verify, review, commit, document) defer to v0.6
per §Bounded scope. Every function has a declared budget from module_01,
consumes the retrieve primitive from module_05, and exposes a stable
output contract the next function reads.

**Intent.** Land `src/ract/memory/functions/{__init__,intake,research,
plan,edit}.py` plus the four output-contract dataclasses (`WorkOrder`,
`ResearchBundle`, `ChangePlan`, `CandidateDiff`) at
`src/ract/memory/functions/contracts.py`. Each function reads its budget
from `budget_registry.get(function_name)`, assembles context via the
retrieve primitive, calls the provider through the existing `providers/`
layer, and writes its output to session memory. Every function is a
composable unit under module_07's playbook runner and a `SubstrateStepSpec`
under module_09's SubstrateLoop wiring.

## Steps

1. **Read** the prior surfaces this module consumes.
   - `src/ract/memory/budget.py` and `budget_registry.py` (module_01) —
     every function's budget.
   - `src/ract/memory/retrieve.py` (module_05) — the retrieval
     primitive.
   - `src/ract/providers/` — the existing provider layer. This module
     invokes providers via the existing `ProviderRouter` and
     `Provider.send()` interface; no change to the provider layer.
2. **Add** `src/ract/memory/functions/contracts.py`:
   - `WorkOrder(dataclass, frozen)` — `request_type: Literal[<enum>]`,
     `scope_hints: ScopeHints`, `success_criteria: tuple[str, ...]`,
     `constraints: tuple[str, ...]`, `priority_markers: dict[str, str]`,
     `ambiguity_flags: tuple[str, ...] = ()`.
   - `ResearchBundle(dataclass, frozen)` — `relevant_symbols:
     tuple[SymbolWithRationale, ...]`,
     `call_neighborhood: tuple[SignatureRow, ...]`,
     `architectural_context: str`,
     `similar_prior_work: tuple[CommitRef, ...]`,
     `risk_zones: tuple[SymbolRef, ...]`.
   - `ChangePlan(dataclass, frozen)` — `target_symbols:
     tuple[TargetSymbol, ...]`,
     `load_manifest: tuple[SymbolRef, ...]`,
     `invariants: tuple[Invariant, ...]`,
     `verification_criteria: tuple[VerificationCriterion, ...]`,
     `risk_assessment: RiskAssessment`,
     `iteration_bound: int`.
   - `CandidateDiff(dataclass, frozen)` — `unified_diff: str`,
     `hunks: tuple[HunkSummary, ...]`,
     `assembled_input_tokens: int`,
     `output_tokens: int`.
3. **Add** `src/ract/memory/functions/intake.py`:
   - `intake(request: str, repo_root: Path, ctx: IntakeContext,
     provider: Provider) -> WorkOrder`.
   - Budget from `budget_registry.get("intake")`.
   - Retrieval: recent git log (last 10 commits, summaries only via
     `git log --oneline -n 10`), README top section (via file read),
     any explicitly mentioned files' signatures (via
     `retrieve(query=RetrievalQuery(symbol_names=[mentioned_symbols]),
     ..., format=SIGNATURE)`).
   - Provider call: `provider.send(prompt, budget)`; parse response
     via the AST-shaped JSON contract at
     `src/ract/memory/functions/prompts/intake_v1.md`.
   - On ambiguity: return WorkOrder with `ambiguity_flags` populated.
4. **Add** `src/ract/memory/functions/research.py`:
   - `research(work_order: WorkOrder, indexes: IndexBundle, provider:
     Provider) -> ResearchBundle`.
   - Budget from `budget_registry.get("research")`.
   - Retrieval per master spec §research pattern: repo map, symbol
     index for named symbols, FTS on docstrings, semantic top 10 by
     signature, graph one-hop signatures, git log grep for keywords
     top 5.
   - Provider call: `provider.send(prompt, budget)`; parse response
     via `research_v1.md`.
   - On empty relevant_symbols: raise `EmptyResearchError` (composition
     layer decides to reindex-and-retry or escalate).
   - On more than 50 relevant_symbols: run one recursive narrowing pass
     with tighter scope hints; if still oversized, raise
     `OversizedResearchError`.
5. **Add** `src/ract/memory/functions/plan.py`:
   - `plan(work_order: WorkOrder, research: ResearchBundle,
     indexes: IndexBundle, provider: Provider) -> ChangePlan`.
   - Budget from `budget_registry.get("plan")`.
   - Retrieval: initial pass reads the research bundle; may issue
     mid-invocation `retrieve` calls under scoped sub-budgets (500
     tokens each, max 3 calls, bounded by module_05's
     `NestedRetrievalError`).
   - Provider call: `provider.send(prompt, budget)`; parse response
     via `plan_v1.md`.
   - On infeasible: return ChangePlan with `status=infeasible`
     (composition escalates).
   - The `verification_criteria` are emitted as `AcceptancePredicate`
     values that module_09 wires into the SubstrateLoop's
     `SubstrateStepSpec.predicates`.
6. **Add** `src/ract/memory/functions/edit.py`:
   - `edit(plan: ChangePlan, indexes: IndexBundle, provider: Provider)
     -> CandidateDiff`.
   - Budget from `budget_registry.get("edit")`.
   - Retrieval: load actual code for symbols in `plan.load_manifest`.
     FULL for `target_symbols`. BODY_ONLY for symbols called by
     targets. SIGNATURE for wider neighborhood.
   - Cascade: if load_manifest FULL exceeds input budget, downgrade
     to SIGNATURE for neighborhood, then BODY_ONLY for referenced-
     but-unmodified, then raise `BoundedContextError` if targets
     themselves exceed budget (composition splits plan or escalates).
   - Provider call: `provider.send(prompt, budget)`; parse response
     via `edit_v1.md`.
   - Output validation: tree-sitter parse the post-patch file for
     every hunk; on parse error, retry up to 2 times with the parse
     error as additional context. Grammar-constrained generation
     (Outlines) defers to v0.6.
7. **Add** `src/ract/memory/functions/prompts/`:
   - `intake_v1.md`, `research_v1.md`, `plan_v1.md`, `edit_v1.md`.
   - Each prompt names the function's contract, the input schema, and
     the required output schema. No em-dashes, no "not X but Y", no
     AI-vocabulary. Direct declarative sentences.
   - Every prompt file has a `# Contract version: v1` header for
     later migration.
8. **Add** `src/ract/memory/session.py`:
   - `SessionMemory` — a per-run store for WorkOrder, ResearchBundle,
     ChangePlan, CandidateDiff. Written by each function, read by the
     next. Persisted to `evals/runs/<run_id>/session.json` after
     every write.
9. **Tests** — new files under `tests/memory/`:
   - `tests/memory/test_intake.py` — intake against a fixture request
     ("rename the User class to Account") returns a WorkOrder with
     `request_type=refactor`, `scope_hints.mentioned_symbols=["User"]`,
     and no ambiguity flags. Uses a mock Provider that returns the
     canonical schema.
   - `tests/memory/test_research.py` — research against a WorkOrder
     for the tiny_repo returns a ResearchBundle with the expected
     symbols and a call_neighborhood of the correct size.
   - `tests/memory/test_plan.py` — plan against a WorkOrder +
     ResearchBundle returns a ChangePlan with `load_manifest` covering
     every file that references the renamed symbol.
   - `tests/memory/test_edit.py` — edit against a ChangePlan returns
     a CandidateDiff whose unified_diff parses cleanly against the
     workspace; a mock provider that returns invalid syntax triggers
     the retry path.
   - `tests/memory/test_functions_contracts.py` — every dataclass is
     frozen; a mutation attempt raises; canonical JSON serialization
     roundtrips.
10. **Docs:**
    - Add ADR-0036: "Four v0.5.0 function contracts (intake/research/
      plan/edit); verify/review/commit/document deferred to v0.6."
      Cover the split justification per master spec §Bounded scope.
    - Add a new section to `docs/ARCHITECTURE.md`: "Function contracts
      (v0.5.0 memory discipline)." Cross-link to master spec §Function
      contracts.

## Lateral Chain pass (PRE-build)

**Branches:**

- A: **Provider adapter mismatch.** The existing `providers/` layer
  expects a specific input format; the new function contracts pass
  richer context (system prompt + function contract + state + bundle +
  input). Merge branch — the module invokes providers through a new
  adapter at `src/ract/memory/provider_adapter.py` that composes the
  five sections per master spec §Context composition before calling
  `provider.send()`. Carry forward.
- B: **Mock provider for tests.** Every function test needs a
  provider stub. Merge branch — a new `src/ract/memory/testing/
  mock_provider.py` returns canned responses keyed on the assembled
  prompt hash; tests parameterize the canned response per test case.
- C: **Prompt versioning.** `intake_v1.md` today; `intake_v2.md`
  tomorrow. If the function reads a hard-coded filename, migrating
  requires a code change. Merge branch — the function reads
  `prompts/{function}_{version}.md` where `version` is a constant in
  the function module (`INTAKE_PROMPT_VERSION = "v1"`); a version
  bump is a one-line edit plus a new prompt file. Carry forward.
- D: **Error path uniformity.** Each function has its own error
  types (`EmptyResearchError`, `BoundedContextError`,
  `InvalidSyntaxError`). Composition needs a single try/except.
  Merge branch — a common base `MemoryFunctionError(RuntimeError)`
  is the parent of all four; composition catches the base and
  dispatches per subclass. Carry forward.
- E: **What if a plan produces a ChangePlan that doesn't reference
  every symbol edit will need to touch?** Edit hits the cascade,
  splits the plan, and the composition layer loops back to plan.
  Merge branch — the plan/edit loop is bounded by
  `ChangePlan.iteration_bound` (default 3); an unbounded loop is
  refused at the plan level. Carry forward.

**Prune:** keep A, B, C, D, E. All five change intent shape.

**Up-intent verify:** sharper. A closes the provider-mismatch worry;
B closes the test-stub worry; C closes the prompt-migration worry; D
closes the try/except uniformity worry; E closes the plan/edit
recursion worry.

## Depth Chain pass (PRE-build)

**Load-bearing assumption.** The existing `providers/` layer's
`Provider.send(prompt, budget)` signature accommodates the assembled
5-section context under the current budget declarations. If a
provider's SDK enforces a lower ceiling than the function's declared
`hard_ceiling`, the provider adapter must downgrade the assembly
before the send. First live run under this module verifies via a
`scripts/memory/smoke_functions.py` that each function completes a
round-trip against the mock provider using the fixture repo.

**Core dependency.** module_05's `retrieve` primitive is stable and
its `RetrievalBundle` shape is committed. If module_05's bundle
shape changes, every function in this module updates its consumer
call. The Depth Chain leaf (a) below verifies against the module_05
API surface.

**Leaves.**

- **Depth 4 leaf (a):** `src/ract/memory/functions/*.py` all import
  cleanly against the module_05 `retrieve` signature; `pytest -q
  tests/memory/test_intake.py tests/memory/test_research.py
  tests/memory/test_plan.py tests/memory/test_edit.py
  tests/memory/test_functions_contracts.py` runs green.
- **Depth 4 leaf (b):** smoke script `scripts/memory/smoke_functions.
  py` completes a round-trip against the mock provider using the
  tiny_repo fixture.
- **Depth 4 leaf (c):** every function's contract dataclass is
  frozen; a mutation attempt raises `FrozenInstanceError`; canonical
  JSON serialization roundtrips.
- **Depth 4 leaf (d):** ADR-0036 exists; `docs/ARCHITECTURE.md` has
  a new "Function contracts" section.

## Reasoning Endpoints for scoping

**Producer:** NVIDIA `code` (Qwen3 Coder 480B). Role: draft the four
function implementations, the shared contract dataclasses, and the
provider adapter.

**Reviewer:** an OpenRouter reasoning function cross-family from Qwen3 Coder (operator selects the specific function from the current OpenRouter catalog at dispatch time) (cross-family from Qwen3
Coder). Documented fallback if OpenRouter's budget is exhausted:
Google Gemini flash reasoning function.

**Why the pair provides blind-spot diversity.** Qwen3 Coder writes
idiomatic Python; the OpenRouter cross-family reviewer reviews contract stability and
composition semantics. Concrete review question: "Do the four
function contracts compose transitively — that is, can plan's
ChangePlan be consumed by edit without any lossy conversion, and can
research's ResearchBundle be consumed by plan without missing fields
plan needs to compute load_manifest?"

## Second Pass discipline

After the first-build subagent lands the code plus tests and the DoD
is boolean-passing, the diff plus master-spec §Function contracts quote
plus the four function tests go to an OpenRouter reasoning function cross-family from Qwen3 Coder (operator selects the specific function from the current OpenRouter catalog at dispatch time) for
skeptical review. Same reviewer named in the scoping section.
Fallback: Google Gemini flash reasoning function.

**Adversarial questions the reviewer is asked:**

1. Do the four function contracts compose transitively (see scoping
   question)? Name any missing field or lossy conversion.
2. `intake` writes ambiguity_flags on ambiguous requests. Does the
   composition layer read those flags and route to human clarification,
   or does research consume the ambiguous WorkOrder and silently
   proceed with best-effort scope hints?
3. `edit`'s retry-on-parse-error is bounded at 2. If the provider
   returns invalid syntax three times in a row, does the function
   raise a specific error naming the parse issue, or does it silently
   return the last (invalid) diff?
4. The prompt version constant is a code-level string. If someone
   ships `intake_v2.md` without bumping `INTAKE_PROMPT_VERSION`, the
   function silently continues using v1. Is there a startup check
   that would flag the mismatch?

**Two possible outcomes.** Same protocol as module_01-05.

## Second Pass results

**Reviewer:** OpenRouter `reason_nemotron_ultra` (NVIDIA Nemotron 3
Ultra 550B via OpenRouter, cross-family from producer NVIDIA Qwen3
Coder 480B). Response at
`_BUILD/ract_v0.5.0_memory_discipline/second_pass/module_06_review_response.txt`.

- **Q1 CONFIRMED (no fix).** Four contracts compose transitively.
  `ChangePlan.{target_symbols, load_manifest}` cover every field
  `edit._assemble_load_block` needs. `plan._state_block` serialises
  the full `ResearchBundle` (contracts.py:200-230, edit.py:200-250,
  plan.py:140-145). No missing seam.
- **Q2 CONFIRMED (fix landed inline).** `research()` did not read
  `work_order.ambiguity_flags`; a silently-ambiguous WorkOrder
  proceeded with best-effort scope hints. Fix: `research.py:127-140`
  now emits a `budget.declared` event carrying
  `ambiguity_flags` when non-empty, so the composition layer's
  clarification gate sees the signal in the trace even when it
  elects to proceed. Regression test
  `test_research_ambiguity_flag_emits_visible_event` in
  `tests/memory/test_functions_contracts.py` pins the fix.
- **Q3 CONFIRMED (no fix).** After 3 failed attempts
  (`MAX_PARSE_RETRIES=2`, initial + 2 retries), `edit` raises
  `InvalidSyntaxError` with `payload["parse_error"]` naming the
  last failure. Never returns invalid diff. Test
  `test_edit_retries_on_invalid_diff_syntax` pins it.
- **Q4 PARTIAL (fix landed inline).** `assert_prompt_shipped` is
  one-directional: constant -> file only. A prompt file added
  without a matching constant stays silent. Fix: added
  `verify_prompt_coverage(expected: dict[str, str])` in
  `prompts_loader.py` that scans `PROMPTS_DIR` and asserts every
  file matches a known constant, and vice versa. Two regression
  tests pin the fix (`test_verify_prompt_coverage_passes_for_shipped_constants`
  + `test_verify_prompt_coverage_raises_on_extra_file`).

Reviewer notes acknowledged but not fixed (logged as Flagged gaps):

- `IntakeContext.selected_code` is carried but documented as "kept
  out of the assembled prompt" — Flagged gap 1.
- `plan.mid_invocation_queries` has no composition-layer wiring
  yet — Flagged gap 2 (module_07 owns the wiring).
- `edit._validate_diff` adds FIXME/XXX/NotImplementedError beyond
  the master-spec list — defensible hardening but note it in the
  spec — Flagged gap 3.

## Lateral Chain pass (POST-audit)

Applied against the FINISHED module + Second Pass verdicts.

**Branches:**

- **POST-A: Ambiguity-flag propagation as a trace-only signal.**
  Q2 fix emits `ambiguity_flags` on the `budget.declared` payload
  when the WorkOrder has any. That surfaces in the null-sink today
  and (once module_09 wires the real sink) in the event trace. But
  the composition layer (module_07) that reads the trace and gates
  the human-clarification route does not exist yet. Merge branch —
  the signal is present but unread until module_07 lands the
  playbook composition runner. Carry forward as inbound constraint
  for module_07.
- **POST-B: Prompt coverage check is opt-in.**
  `verify_prompt_coverage` is a callable, not a startup check;
  the four `assert_prompt_shipped` calls at function import time
  still only check constant -> file. A shipped-CLI wiring that
  calls `verify_prompt_coverage` from `ract memory init` (or from
  the SubstrateLoop startup) is the load-bearing invocation. Merge
  branch — carry forward as inbound constraint for module_09 CLI
  wiring.
- **POST-C: The Q2 fix routes through `emit_budget_declared` rather
  than a dedicated event kind.** Reusing the existing event kind
  keeps the closed EventKind vocabulary intact but overloads the
  `budget.declared` payload with an ambiguity semantic. A
  dedicated `workorder.ambiguous` event kind would be cleaner
  but requires bumping the closed vocabulary. Prune — module_09
  owns the closed-vocabulary bump; treating the overload as a
  transitional shape (documented in the fix comment) is honest.
- **POST-D: The four contracts pass tuples of `(str, str)` for
  key/value payloads (priority_markers, verification_criteria
  .payload) rather than `dict[str, str]`.** This keeps the
  dataclasses frozen at every level, but a caller building a
  contract has to sort the tuple to match canonical form. Merge
  branch — the canonical-JSON round-trip test pins the shape, and
  the `_parse_response` helpers sort at construction, but a
  future contract-builder helper module would smooth the surface.
  Carry forward as v0.6 hardening.
- **POST-E: `SessionMemory` is single-writer per file; concurrent
  runs against the same `session_path` race.** The persistence is
  a straight `path.write_text(json.dumps(...))` under a `mkdir(...)`;
  two runs against the same path clobber each other. Prune — every
  run has a unique `evals/runs/<run_id>/session.json` path per
  master spec §Function contracts, so the race is out of scope
  today. Note in the ADR that reuse of the same session_path is
  caller error.

**Prune:** keep A, B, D. Prune C (documented overload) and E
(unique-per-run path invariant makes it moot).

**Up-intent verify:** sharper. A + B name concrete downstream
work; D flags a v0.6-scoped ergonomic hardening.

## Depth Chain pass (POST-audit)

Applied against the FINISHED module.

**Load-bearing assumption from PRE-build:** "The existing
`providers/` layer's `Provider.send(prompt, budget)` signature
accommodates the assembled 5-section context under the current
budget declarations."

**CHECKED as delivered.** REFINED. The module shipped a new
protocol `MemoryFunctionProvider` at
`src/ract/memory/functions/provider_adapter.py:35-45` with a
`send(prompt: str, declaration: BudgetDeclaration) -> str`
signature, distinct from `ract.providers.base.ProviderAdapter.
complete(messages, model, ...)`. Module_09 wires the bridge; until
then tests use `MockProvider`. The `assemble_prompt` five-section
composer at `provider_adapter.py:56-80` sits between the four
functions and the model call. Smoke script confirms round-trip
against `MockProvider` (`scripts/memory/smoke_functions.py`).

**Core dependency from PRE-build:** "module_05's `retrieve`
primitive is stable and its `RetrievalBundle` shape is committed."

**CONFIRMED as delivered.** Every function consuming retrieve
does so through the module_05 primitive without re-implementing
the cascade: `research._run_retrieval` (research.py:220-240) at
SIGNATURE format + CORE_FIRST strategy; `plan` at
`plan.py:88-110` with `depth=1` for mid-invocation sub-retrieves;
`edit._assemble_load_block` at `edit.py:220-290` runs its own
FULL -> SIGNATURE -> BODY_ONLY -> targets-only tier cascade on top
of the primitive.

**Leaves.**

- **Depth 4 leaf (a) — full memory-suite green + all four function
  tests pass.** `pytest tests/memory/ --no-cov -q` returns
  `320 passed, 2 skipped` at close (was 317 pre-SP-fix; +3 from
  the two `verify_prompt_coverage` tests + the ambiguity-flag
  emission test). Verifies the parent Intent "land the four
  function contracts and their tests" is delivered.
- **Depth 4 leaf (b) — smoke round-trip green.**
  `scripts/memory/smoke_functions.py` completes and prints
  `smoke ok: 1 hunk(s)`. Verifies the parent Intent "each function
  is a composable unit" — the intake -> research -> plan -> edit
  chain runs end-to-end against MockProvider.
- **Depth 4 leaf (c) — every contract dataclass is frozen +
  canonical JSON round-trip pins.** `tests/memory/
  test_functions_contracts.py` includes
  `test_contract_is_frozen` (parametrized across 4 contracts),
  `test_scope_hints_is_frozen`, `test_json_round_trip`
  (parametrized), `test_work_order_json_is_canonical`,
  `test_json_projection_is_sorted`. Verifies the parent Intent
  "expose stable output contracts the next function reads".
- **Depth 4 leaf (d) — ADR-0036 + ARCHITECTURE section land.**
  `docs/ADRs/ADR-0036-function-contracts.md` exists (185 lines);
  `docs/ARCHITECTURE.md` §Function contracts section exists at
  the tail of the retrieve primitive section. Verifies the parent
  Intent "documented v0.5.0 scope choice + v0.6 deferral".

## Inbound constraints for later modules

Module_06 surfaces the following for modules 07 / 08 / 09 to honor
at their own POST time:

1. **Module_07 (playbook composition) MUST wire the ambiguity-
   flag route.** POST-A: the Q2 fix emits `ambiguity_flags` on
   the `budget.declared` event when a WorkOrder is ambiguous.
   Module_07's playbook composition runner reads the trace and
   is the gate that routes to human clarification. Without
   module_07's read, the signal exists in the trace but no one
   acts on it.
2. **Module_07 MUST supply `plan.mid_invocation_queries`.** Reviewer
   note: `plan()` accepts up to 3 queries at 500 tokens each but
   nothing supplies them today. Module_07's playbook YAML is the
   configuration surface (e.g. bug_fix's "reproduce" step could
   emit a mid-invocation query for a failing-test's neighbourhood).
3. **Module_09 (SubstrateLoop wiring) MUST invoke
   `verify_prompt_coverage` at startup.** POST-B: the coverage
   check is a callable, not an import-time invariant. Wire it into
   `ract memory init` (or SubstrateLoop startup) so a shipped
   `intake_v2.md` without a matching constant bump fails loudly.
4. **Module_09 MUST bridge `MemoryFunctionProvider.send` to
   `ract.providers.base.ProviderAdapter.complete`.** The
   `assemble_prompt` composer returns a single string; the
   providers layer expects `messages: list[dict[str, str]]`. The
   bridge lands in module_09 as a small adapter (one
   `{"role": "user", "content": prompt}` message; system section
   already carries the role).
5. **Module_09 SHOULD wire `edit`'s CandidateDiff into ALM Gate
   G6 (under-edit closure) and Gate G7 (companion provider).**
   Master spec §Integration surface item 5 names this; module_06
   ships the CandidateDiff shape; module_09 wires the gate
   invocation.
6. **Module_08 (probes) MAY use `MockProvider` for its needle /
   coherence / adherence fixtures.** The probe harness needs a
   canned-response provider; `ract.memory.functions.testing.
   mock_provider.MockProvider` is the shipped shape.
7. **Module_07 (playbook composition) inherits the knapsack
   packing decision (module_05 POST constraint 1).** Module_06's
   four functions consume `retrieve()`'s greedy per-level pack;
   the plan/edit cascade in module_06 does not implement O(n*B)
   DP knapsack. Module_07's playbook budgets are where the
   packing strategy decision can migrate if the greedy floor
   is insufficient in practice.

## Depth Chain pass (POST-audit) — DEPRECATED PLACEHOLDER (kept for skill parity)

_(POST-audit depth chain landed inline above under Second Pass
results. This heading kept so the module.md structure matches
prior modules; content is above.)_

## Definition of Done

- `src/ract/memory/functions/__init__.py`, `contracts.py`,
  `intake.py`, `research.py`, `plan.py`, `edit.py`, `session.py`
  all exist with the API listed in steps 2-8.
- Prompt files `prompts/{intake,research,plan,edit}_v1.md` all exist.
- Each function reads its budget from `budget_registry.get(name)`.
- Each function invokes providers via the new provider adapter.
- Every contract dataclass is frozen; canonical JSON serialization
  roundtrips.
- Smoke script `scripts/memory/smoke_functions.py` completes a
  round-trip against the mock provider using the tiny_repo fixture.
- `pytest -q tests/memory/test_intake.py tests/memory/test_research.py
  tests/memory/test_plan.py tests/memory/test_edit.py
  tests/memory/test_functions_contracts.py` runs green.
- `ruff check src/ract/memory/`, `mypy src/ract/memory/`, and full
  `pytest -q` all clean.
- ADR-0036 exists; `docs/ARCHITECTURE.md` has a new "Function
  contracts" section.
- Closed-IP wordlist scan: zero hits.
- Second Pass complete.

## Reference sources

- MEMORY DISCIPLINE spec §Function contracts, §Bounded scope,
  §Signals item 8.
- `src/ract/providers/` — the existing provider layer.
- Substrate module_04 (`_BUILD/ract_v0.4.0_substrate/module_04.md`)
  for the typed-action-union pattern the contracts mirror.
- ALM module_04 (`_BUILD/ract_v0.4.0_antilazy/module_04.md`) for
  the companion-provider integration pattern edit will extend in
  module_09.

## Flagged gaps (to log at close)

1. **`IntakeContext.selected_code` shape drift.** Reviewer note.
   The field is documented as "kept out of the assembled prompt"
   (`intake.py:194`) but is still a dataclass field. Either drop
   the field or explicitly seat its bytes on a separate accountant
   section so the "kept out" note becomes enforcable. Owner: v0.6
   hardening.

2. **`plan.mid_invocation_queries` composition wiring.** Reviewer
   note. `plan()` accepts up to `MAX_MID_INVOCATION_RETRIEVES=3`
   queries at 500-token sub-budgets each, but nothing supplies
   them in v0.5.0 — module_07's playbook YAML is where the
   `bug_fix.reproduce` step (per master spec §Bug fix) would
   emit a mid-invocation query. Owner: module_07 (playbook
   composition).

3. **`edit._validate_diff` extends the master-spec forbidden-
   token list.** Reviewer note. Master spec §edit output
   discipline listed "no TODO, no ellipsis bodies, no 'leave X
   unchanged' prose". Shipped implementation also refuses
   `FIXME`, `XXX`, `pass  # implement`, and `raise
   NotImplementedError`. Defensible hardening; spec should be
   updated to name the full list explicitly. Owner: v0.6 spec
   update or module_10 release close.

4. **Outlines grammar-constrained generation for edit.** ADR-0036
   §Alternative 3. v0.5.0 ships the lightweight post-generation
   validator; grammar-constrained generation via Outlines defers
   to v0.6. When landed, the validator stays as defence-in-depth.
   Owner: v0.6 pipeline.

5. **`priority_markers` / `verification_criteria.payload` are
   tuple-of-tuple instead of dict.** POST-D. Keeps every level
   of every contract frozen, but a caller building a contract
   has to sort the tuple to match canonical form. A contract-
   builder helper module (v0.6) would smooth the surface.
   Owner: v0.6 hardening.

6. **Ambiguity-flag route lands as a trace-only signal today.**
   POST-A. The Q2 fix emits `ambiguity_flags` on
   `budget.declared`, so the composition layer that eventually
   reads the trace can gate; but that composition layer is
   module_07's playbook runner, which does not exist yet. The
   flag is present in the trace but unread until then. Owner:
   module_07 (playbook composition).

7. **`verify_prompt_coverage` is opt-in.** POST-B. The reverse
   drift check (a shipped prompt file without a matching
   constant) is now available as a callable, but nothing invokes
   it at startup. Module_09's SubstrateLoop startup or the
   `ract memory init` CLI is where the invocation lands. Owner:
   module_09 (SubstrateLoop wiring).

8. **Knapsack packing across function call sites.** Carried
   forward from module_04 POST constraint 1 and module_05 POST
   constraint 1. The four function contracts use the retrieve
   primitive's greedy per-level pack. A 0/1 knapsack DP at
   O(n*B) or a k-approximation would pack tighter under
   pressure. Owner: module_07 (playbook budgets can migrate the
   packing strategy) or v0.6 hardening.

9. **SUMMARY provider adapter.** Carried forward from module_05
   Flagged gap 2. `format_chunk(chunk, ChunkFormat.SUMMARY,
   provider=None)` returns `"summary unavailable"` +
   `summary_pending=True`. Module_06 ships the four function
   contracts but does not wire a summariser provider. The
   MemoryFunctionProvider protocol shape (`send(prompt,
   declaration) -> str`) is a fit for a wrapping summariser
   adapter; module_09's provider registry is the natural home.
   Owner: module_09 (provider registry + SubstrateLoop wiring).
