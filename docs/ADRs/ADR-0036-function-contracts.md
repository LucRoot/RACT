# ADR-0036 — Four v0.5.0 function contracts (intake / research / plan / edit)

Status: accepted (v0.5.0 Memory Discipline, module_06).

## Context

The memory-discipline pipeline composes four indexed retrieve calls
per model invocation (budget accountant, symbol / graph / semantic
indexes, retrieve primitive). Master spec §Function contracts names
eight verbs that carry a change through the pipeline (`intake`,
`research`, `plan`, `edit`, `verify`, `review`, `commit`,
`document`). v0.5.0 lands the first four; the remaining four defer
to v0.6.

The load-bearing questions:

- Which contract shape does each verb emit so the next verb consumes
  it without lossy translation?
- Where does the boundary between the retrieve primitive (module_05,
  transport-agnostic) and a function's model call live?
- How does the edit function enforce diff quality without introducing
  a grammar-constrained-generation dependency (Outlines) that would
  drag ``torch`` into the runtime install?

## Alternatives considered

**1. Ship all eight verbs in v0.5.0.** Cleanest surface: one release,
one composition graph, no follow-on migration. Rejected because
`verify` / `review` / `commit` / `document` are downstream of `edit`
and can be satisfied today by the deterministic tools already in the
tree (tree-sitter parse, pytest, ast-grep). Shipping them under a
memory-discipline contract adds shape but no capability; the four
v0.5.0 verbs cover the load-bearing path (request → diff).

**2. Ship contracts as protocol classes rather than frozen
dataclasses.** Protocol classes let callers substitute their own
implementations. Rejected because the contracts are data records,
not services — a protocol shape hides the round-trip guarantee. The
frozen-dataclass shape closes the mutation attack surface and makes
canonical JSON round-trip a testable invariant.

**3. Wire Outlines for grammar-constrained generation in edit.**
Master spec §edit output discipline names Outlines as the "ideal"
diff-generation constraint. Rejected for v0.5.0: Outlines drags
``torch`` into the runtime install, doubles the install footprint,
and hides a heavy dep behind an "optional" wrapper. The v0.5.0
edit function ships a post-generation validator instead (lazy-token
scan + ellipsis-body check + prose-placeholder check); grammar-
constrained generation defers to v0.6 as a Flagged gap.

**4. Ship the four v0.5.0 verbs + defer the other four (accepted).**
Every v0.5.0 verb is a `SubstrateStepSpec` under module_09's
wiring; every one reads its budget from
`ract.memory.budget_registry.get`; every one consumes
`retrieve()` from module_05 and returns a frozen contract from
`ract.memory.functions.contracts`. The four contracts compose
transitively: `intake` → WorkOrder → `research` → ResearchBundle →
`plan` → ChangePlan → `edit` → CandidateDiff. The remaining four
verbs (`verify`, `review`, `commit`, `document`) sit downstream of
`edit`'s CandidateDiff and can be added in v0.6 without reshaping
the v0.5.0 surface.

## Decision

Land four function modules at `src/ract/memory/functions/`
(`intake.py`, `research.py`, `plan.py`, `edit.py`), four frozen
output contracts (`WorkOrder`, `ResearchBundle`, `ChangePlan`,
`CandidateDiff`) at `contracts.py`, four prompt files at
`prompts/{function}_v1.md`, a common error hierarchy at `errors.py`
with `MemoryFunctionError` as the composition-catch base class, a
transport-agnostic provider adapter at `provider_adapter.py`, a
canned-response mock provider at `testing/mock_provider.py`, a
per-run store at `session.py`, and a smoke script at
`scripts/memory/smoke_functions.py`.

Every function:

1. Reads its budget via `budget_registry.get(name)`.
2. Assembles the five-section prompt via `assemble_prompt`.
3. Refuses over-ceiling via `refuse_over_ceiling` before any model
   call (the sacred-spine invariant).
4. Delegates the model call to a `MemoryFunctionProvider.send`.
5. Parses the response against the JSON contract in the paired
   prompt file.

Prompt versioning ships as a code-level constant per function
(`INTAKE_PROMPT_VERSION = "v1"` etc.). The `assert_prompt_shipped`
helper fires at import time, so a version-string bump without a
matching prompt file surfaces before the first invocation.

Edit output discipline ships as a lightweight post-generation
validator:

- Non-empty diff text.
- At least one hunk header (`@@`) or file marker (`+++` / `---`).
- No forbidden tokens (`TODO`, `FIXME`, `XXX`, `raise NotImplementedError`).
- No standalone ellipsis (`...`) statement bodies.
- No lazy-prose placeholders (`leave X unchanged`, `rest omitted`).

Failures retry up to twice with the validator's reasons appended to
the prompt. Third failure raises `InvalidSyntaxError` naming the
last parse error.

## Consequences

- The composition layer (module_07 playbook runner) catches
  `MemoryFunctionError` once and dispatches per subclass. New verbs
  in v0.6 subclass the same base.
- The transport-agnostic provider adapter means tests never talk to
  a live provider. Module_09 wires the real
  `MemoryFunctionProvider` that bridges to
  `ract.providers.base.ProviderAdapter.complete`.
- The lazy-token validator is a floor, not a ceiling. A future
  release can add grammar-constrained generation on top; the
  validator stays as a defence-in-depth check.
- The `SessionMemory` file persists the four records to
  `evals/runs/<run_id>/session.json`. A cross-session reader can
  rehydrate via `SessionMemory.from_path`.

## References

- Master spec: `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`
  §Function contracts, §Bounded scope, §Signals items 8-9.
- Module map: `_BUILD/ract_v0.5.0_memory_discipline/module_06.md`.
- Precedent for typed-action-union pattern: `docs/ADRs/ADR-0011`.
- Precedent for companion-provider integration: ALM module_04
  (`_BUILD/ract_v0.4.0_antilazy/module_04.md`).
