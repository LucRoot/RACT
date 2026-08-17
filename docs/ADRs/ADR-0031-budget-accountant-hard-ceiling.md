# ADR-0031 — Budget accountant refuses over-ceiling invocations before the model call

Status: accepted (v0.5.0 Memory Discipline, module_01).

## Context

RACT v0.1 shipped ``src/ract/token_budget.py``: a whole-file curator
that ranked candidate context files by relevance and returned the
subset that fit under ``max_tokens``. On over-budget the curator
silently dropped the low-relevance tail. The behavior was suitable
for the early plan/step surface, where the loss of a low-relevance
file was tolerable, but it does not compose with the memory-discipline
pipeline landing under v0.5.0: the pipeline assembles a
system-prompt/function-contract/state-context/retrieved-bundle/
invocation-input structure per function, and a silent drop of any
section leaves the model to hallucinate around the missing slice
without a signal to the caller.

The memory-discipline spec (``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_
SPEC.md`` §The token budget system) requires a per-invocation
accountant that:

1. declares the shape ahead of time (``BudgetDeclaration``),
2. seats every assembled section under a running total,
3. exposes over-target / over-max / over-ceiling predicates so the
   assembly pipeline can invoke the retrieval cascade's downgrade
   path on over-target, refuse the invocation on over-max naming the
   offending section, and refuse the invocation BEFORE the model
   call on over-ceiling emitting ``budget.exceeded`` to the event
   trace.

The load-bearing question is what to do on over-ceiling. Four
alternatives were considered.

## Alternatives considered

**1. Silent soft-degradation (drop low-relevance sections).** The
v0.1 behavior. Refused because:

- the seated total no longer matches what the model actually saw;
- the model has no way to know a section was silently trimmed;
- a downstream test that fails on missing context has no signal to
  correlate against;
- the pipeline's Rootknot attestation carries a retrieval bundle
  hash — a silent drop invalidates the attestation without a visible
  event.

**2. Model-side self-narrowing (model rewrites its own prompt).**
Refused because:

- the narrowing decision needs the token budget shape, which the
  model does not carry;
- a self-narrowed prompt is a new artifact that the trace has to
  re-record and re-attest — infrastructure the v0.5.0 pipeline does
  not ship;
- reviewer's blind-spot question (module_01 second pass): does the
  narrowing actually reduce token cost, or does the model rewrite
  into a rephrasing that is longer than the original? Empirical
  answer: often the second, because the model has no cost signal.

**3. Unbounded assembly with post-hoc truncation.** Refused because:

- truncation loses structural boundaries (a function contract can
  land half-truncated with only the header, leaving the model to
  guess the constraints);
- post-hoc truncation is the pattern that Palisade Research
  documented an RL agent exploiting to overwrite grading logic
  (ALM ADR-0025 reference source): a caller that knows the
  truncation window can craft an assembly where the post-truncation
  slice reads as sabotaged instructions to the model.

**4. Pre-model refuse (accepted).** The accountant is the gate
BEFORE the model call. On over-ceiling
:meth:`BudgetAccountant.refuse_if_over_ceiling` raises
:class:`BudgetExceededError` naming the offending section and emits
``budget.exceeded`` to the event trace. The caller (the four
function contracts in module_06 + the SubstrateLoop wiring in
module_09) is expected to catch the exception, either:

- split the invocation into per-file / per-step edits (Lateral Chain
  branch A: a plan legitimately needing more budget than declared
  becomes a composition of smaller invocations), or
- surface a handshake to the operator asking for a widened budget
  (widening requires a fresh function-default commit; runtime
  narrowing NEVER widens).

## Decision

The budget accountant refuses over-ceiling invocations before the
model call. Enforcement point:
:meth:`ract.memory.budget.BudgetAccountant.refuse_if_over_ceiling`.
Sacred spine test:
``tests/memory/test_budget_ceiling.py::
test_over_ceiling_refuses_invocation_before_model_call``.

The accountant carries a narrowing log per invocation (Lateral Chain
branch E) so a step that started at 8k, narrowed to 6k, then failed
is more diagnostic than a step that just failed at 6k. The log
ships in the ``budget.declared`` event payload at seat time.

The four narrowing paths (composition override, runtime narrowing,
narrow combinator, CLI flag — the last deferred to v0.6) refuse
widening at both construct time (``BudgetNarrowing.__post_init__``)
and helper time (the ``narrow`` and ``apply_*`` functions). The
belt-and-suspenders shape closes the reviewer's Q2 construct-time
bypass question (``narrow(narrow(base, N1), N2)`` cannot produce a
declaration wider than ``base`` for fields both narrowings touch,
because the ``narrow`` combinator validates each entry's ``old``
against the running intermediate).

The playbook override loader refuses unknown fields (a typo like
``input_maxx`` for ``input.max`` surfaces as
:class:`CompositionSchemaError` naming the offender rather than
silently defaulting). The registry loader applies the same discipline
to the shipped defaults YAML.

## Consequences

Positive:

- every over-ceiling assembly is a red event in the trace, not a
  silent drop;
- the exception names the offending section so the failing assembly
  is diagnosable from the exception alone;
- the accountant is pure over ``(declaration, seated_sections)`` so
  tests compose synthetic scenarios without a live provider;
- widening requires a fresh function-default commit — the design
  change is a visible git diff, not a runtime override;
- the module_09 event wiring ships seven event kinds under a null
  sink today, so the emitter helpers can land without bumping the
  frozen ``EventKind`` Literal alias.

Negative / deferred:

- the estimator default (whitespace-split, matching v0.1) under-
  counts BPE tokens for typical code by 20-40 percent; the module_09
  provider wiring swaps this default for a per-provider estimator on
  every adapter that exposes a native tokenizer (Lateral Chain
  branch C carried forward);
- the runtime-narrowing floor (input_target // 2 against the BASE)
  is a heuristic to prevent runaway narrowing (Lateral Chain branch
  B); a fresh calibration in v0.6 may refine the floor;
- per-provider tokenizer plumbing beyond the four v0.5.0 defaults
  and a formal YAML schema validator via Pydantic ship as Flagged
  gaps for v0.6 hardening.

Reference: docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md §The token
budget system, §Sacred spine item 3, §Signals items 1-2.
