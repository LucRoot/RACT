# ADR-0037: Four v0.5.0 playbooks + composition runner

Status: accepted (v0.5.0 Memory Discipline, module_07).

## Context

The four function contracts landed in module_06 (`intake`,
`research`, `plan`, `edit`) can be sequenced into recognisable
workflows: rename a symbol, extract a method, fix a bug, add a unit
test. Master spec §Playbooks names twelve workflows total. v0.5.0
lands four; the remaining eight (security audit, feature endpoint,
migration, code review, performance, dead-code, schema migration,
config change) defer to v0.6.

The load-bearing questions:

- What is the concrete boundary between a playbook (a YAML
  configuration file) and a composition runner (Python code that
  reads the YAML and dispatches the four verbs)?
- How does the runner respect the risk markers module_06 emits
  (specifically the `ambiguity_flags` on the `budget.declared`
  event) without silently proceeding past a signal the composition
  layer is supposed to gate on?
- How does the bug_fix playbook enforce the "no fix without a
  confirmed reproduction" rule from master spec §Bug fix without
  requiring the operator to hand-edit code for every new bug?
- Where does the ergonomic seam for adding a fifth playbook live?
  If it requires a code edit, the extension surface is too narrow;
  if it requires zero validation, a mistyped field silently
  degrades a run.

## Alternatives considered

**1. Ship all twelve playbooks in v0.5.0.** Cleanest surface: one
release, one playbook catalogue. Rejected because the four
deferred-to-v0.6 playbooks (security audit, feature endpoint,
migration, code review, performance, dead-code, schema migration,
config change) sit downstream of one or more of the four v0.6 verbs
(`verify`, `review`, `commit`, `document`). Shipping their YAMLs
without the verbs they compose would mislead callers into thinking
the pipeline reached them when in reality intermediate verbs are
missing.

**2. Defer all playbooks to v0.6.** Symmetric with the four v0.6
verbs. Rejected because the master spec §Signals item 9 names
playbook composition as a v0.5.0 signal; without any playbook to
run, the signal has nothing to observe.

**3. Ship the four v0.5.0 playbooks via a YAML schema + composition
runner (accepted).** Four YAMLs at
`src/ract/memory/playbooks/{refactor_rename,refactor_extract,
bug_fix,unit_test}.yaml` load into a frozen `PlaybookSpec`
dataclass via a validating parser at
`src/ract/memory/composition_runner.py`. A fifth playbook is a new
YAML file plus a directory-scan enumeration
(`list_playbooks()` returns file stems, sorted). No hard-coded
name list.

**4. Hard-code the four playbooks in Python.** Rejected because a
new playbook would require a code edit plus a test update. YAML
carries the composition shape declaratively; the runner is the only
code path that ever needs a change when a new verb lands in v0.6.

## Decision

Land four playbook YAMLs at `src/ract/memory/playbooks/`:

- `refactor_rename.yaml`: intake, research (graph both hops=1),
  plan (split_threshold=5), edit_loop (per_iteration_budget=6000,
  max_iterations=10).
- `refactor_extract.yaml`: intake, research, plan, edit
  (budget_override input_target=6000).
- `bug_fix.yaml`: intake, research, reproduce, plan, edit
  (budget_override input_target=8000).
- `unit_test.yaml`: intake, research, plan, edit
  (budget_override input_target=6000).

Land a composition runner at
`src/ract/memory/composition_runner.py` exposing:

- `PlaybookSpec`, `PhaseSpec`, `PhaseRecord`, `PlaybookResult`
  frozen dataclasses.
- `parse_playbook_payload(payload, source_label) -> PlaybookSpec`
  with strict schema validation (unknown fields raise
  `PlaybookSchemaError` naming the offender).
- `run_playbook(spec, request, repo_root, provider, indexes, ...)`
  dispatch. Phases execute in list order. Verb phases call the
  shipped `intake` / `research` / `plan` / `edit` functions and
  thread outputs via optional `SessionMemory`. The reproduce phase
  is deterministic (subprocess with wall-clock timeout).

Errors form a family under
`ract.memory.functions.errors.MemoryFunctionError`:
`UnknownPlaybookError`, `PlaybookSchemaError`,
`UnconfirmedBugError`, `OversizeTargetError`,
`IterationBoundExceededError`.

Land a playbook loader at
`src/ract/memory/playbooks/__init__.py`:

- `list_playbooks()`: directory scan returning
  `["bug_fix", "refactor_extract", "refactor_rename", "unit_test"]`
  for the shipped set. A fifth YAML dropped in appears without a
  code edit.
- `load_playbook(name)`: reads the file, parses via the composition
  runner's YAML parser, refuses unknown names with
  `UnknownPlaybookError` naming the shipped set.

Ambiguity handling: when `intake` returns a `WorkOrder` with
non-empty `ambiguity_flags`, the runner emits a `budget.declared`
event carrying the flags and adds an `ambiguity_flag: proceeding
with risk marker` note to the intake `PhaseRecord`. The runner
does not halt: the flag is a documented risk marker per master
spec §intake failure modes. Module_06 POST inbound constraint 1
lands here as an event + record note pair; the human-clarification
gate itself is a future v0.6 harness concern.

Reproduce phase (bug_fix only): the runner tries three sources in
order: explicit `reproduce_command` argument, the phase's own
`reproduce_command` field, or a command derived from
`WorkOrder.success_criteria` treating entries that contain `::` or
end in `.py` as pytest node ids. A non-zero exit code confirms
reproduction; a zero exit raises `UnconfirmedBugError` (the test
already passes, so there is nothing to fix). Missing source also
raises. No fix lands without a confirmed reproduction (master spec
§Bug fix).

Extract phase (refactor_extract only): if `edit()` raises the
edit-side `BoundedContextError` for this playbook specifically, the
runner re-raises as `OversizeTargetError` naming the target
function. Lateral Chain branch C (module_07 PRE): the operator is
expected to reduce the function first.

Edit loop phase (refactor_rename only): iterates over files grouped
from `ChangePlan.load_manifest`. The plan's `iteration_bound` is
the hard cap; a manifest exceeding it raises
`IterationBoundExceededError` before the first model call. Lateral
Chain branch E (module_07 PRE): unbounded loops are refused at the
composition layer, not silently.

## Consequences

- Adding a fifth playbook is a one-file change: add
  `src/ract/memory/playbooks/{name}.yaml` matching the shipped
  schema. `list_playbooks()` finds it via directory scan. No code
  edit is required for a playbook that composes the existing four
  verbs.
- The ambiguity-flag route is wired as a trace event + phase-record
  note today. The composition-layer human-clarification gate itself
  waits for the v0.6 harness; module_07 closes the module_06 POST
  inbound-constraint 1 as a "signal is visible, decision remains
  operator's".
- The `plan.mid_invocation_queries` composition wiring (module_06
  Flagged gap 2 / POST inbound constraint 2) is partially closed
  here as a routing surface (`retrieval_overrides` on the plan
  phase can be forwarded in v0.6); the shipped v0.5.0 runner does
  not yet emit `RetrievalQuery` values from the YAML overrides.
- The reproduce phase runs a subprocess. It uses shell dispatch on
  the operator's platform; a `reproduce_command` that fails to
  launch (missing pytest, missing shell) surfaces as
  `UnconfirmedBugError` with the OS error attached.
- The Python-only reproduce heuristic (pytest node ids) is a v0.5.0
  limitation. TypeScript / Rust / Go workflows come with a v0.6
  playbook per language, once the reproduce phase learns to derive
  a command from the language-specific test harness.
- The four v0.6 verbs (`verify`, `review`, `commit`, `document`)
  will attach downstream of `edit` in every playbook that ships
  them; the current runner's phase list is open-ended, so a v0.6
  playbook adds phases after `edit` without a schema change.

## References

- Master spec: `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`
  §Playbooks, §Bounded scope, §Signals item 9.
- Module map: `_BUILD/ract_v0.5.0_memory_discipline/module_07.md`.
- Function contracts: ADR-0036.
- Composition override precedent: `docs/ADRs/ADR-0031-budget-
  accountant-hard-ceiling.md` and
  `src/ract/memory/composition.py`.
- Substrate composition precedent: `_BUILD/ract_v0.4.0_substrate/
  module_02.md` (`StepTransaction` composition).
