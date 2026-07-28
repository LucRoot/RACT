# ADR-0022 — Companion provider with different-provider constraint and static-heuristic effort estimate as completion-path gates

## Status

Accepted. ALM v0.4.0-rc1, module_04.

## Context

The Anti-Lazy Machine (ALM) ships eight gates layered on top of the
substrate. Module_04 lands the last two before the sycophancy /
investigator circuit of module_05:

- **G7 (companion red team, ALM §3.7).** A cold-context second
  provider receives only the intent, the final diff, and the visible
  predicates. Its job is to propose adversarial counterexamples that
  break the completion claim. Surviving counterexamples emit
  `laziness.violated` with `kind="companion_counterexample"` and the
  loop resumes with the counterexamples injected into the next
  planning prompt.
- **G8 (effort reconciliation, ALM §3.8).** Before step one, a
  static-heuristic estimator produces a low-precision effort estimate
  from the workspace (no model in the loop). After T1 fires, realized
  effort is measured from the final diff; a ratio below `tau_effort`
  (default 0.3) on any dimension queues a suspicion prompt and holds
  COMPLETE.

Both gates land on the completion path, both surface to
`laziness.violated`, and both live inside the substrate architecture
already shipped (they extend the router-gated `Provider` protocol and
the acceptance-suite T1 primitive without modifying them).

Module_04 also closes module_01's flagged gap on
`holdout_kind="trivial"`: a per-pipeline trivial-rate ceiling
(`enforce_trivial_rate_ceiling`) refuses to compile a new held-out
suite when the composer's rolling trivial rate exceeds a bound. The
default bound is 0.3 (no more than 30% of intents may compose
trivially over the last 20 compositions).

## Decision

Land G7 and G8 as documented in module_04.md steps 2 and 3. Wire both
to `LoopController` through a small `run_completion_gates` helper
(`ract.antilazy.completion_gate`) that returns a `CompletionGateOutcome`
naming whether COMPLETE is blocked and, when blocked, the resume
prompt to inject into the next planning turn. Extend the router-gate
`GateConfig` with `anti_lazy_conformance: float = 0.7`; providers
below the floor are refused for both primary and companion roles.
Publish `evals/conformance/COMPANION_MATRIX.md` from the conformance
state via `evals/leaderboard/update_companion_matrix.py`.

Land the trivial-rate ceiling in `ract.antilazy.holdout` as
`enforce_trivial_rate_ceiling` + `TrivialRateCeilingExceededError` +
`HoldoutCompilationRecord`; `compose_held_out` calls the check before
dispatching to the composer.

## Rejected alternatives

- **Same-provider companion.** Reduces cost and simplifies wiring, but
  defeats the point: shared training regimes share blind spots. The
  companion's job is to see what the primary cannot. We keep an
  explicit escape hatch (`deployment_mode="single_provider_advisory"`)
  for deployments with only one provider account, but findings there
  are advisory rather than hard blocks so the operator gets a signal
  without pretending it is a red team.
- **Model-based effort estimate.** A model that produces the estimate
  is the same model that then has to meet it. Any framing the primary
  provider chooses at intent time propagates into the estimate. A
  static heuristic keeps the estimator honest — no model call, no way
  to game the number through intent framing. The Second Pass adversarial
  Q3 (keyword-packing to inflate the estimate) is answered by the
  filename-fraction filter: keywords that hit more than half the
  workspace are dropped as low-signal.
- **Companion running with full workspace write access.** The
  companion becomes a second attack surface if it can modify the
  workspace. Read-only mount (branch A) is a load-bearing invariant;
  `CompanionConfig.read_only = True` is refused by `__post_init__`
  when set False.
- **Effort reconciliation as advisory only.** An advisory G8 defeats
  the point — a model that under-delivers gets a warning and moves on.
  We block COMPLETE until the primary either enumerates skipped items
  with justification or produces additional work that closes the
  anomaly. The suspicion prompt (`suspicion_prompt_text`) names each
  anomalous dimension explicitly.
- **Trivial-rate ceiling as a soft warning.** A warning that the
  compiler can log and continue past reintroduces the module_01
  flagged gap under a different name. We refuse compile
  (`TrivialRateCeilingExceededError`) so the pattern is loud instead
  of silent.

## Consequences

- Every T1 completion now runs two extra checks (G7 and G8). G7 costs
  one companion dispatch (capped at 2 minutes wall time per branch B);
  G8 is a pure static heuristic and adds microseconds.
- Providers below `anti_lazy_conformance=0.7` are refused at router
  registration. Older conformance reports produced before ALM shipped
  omit the `anti_lazy` category; the gate treats that as "not scored"
  and admits the provider so v0.3 CLI paths continue to work. New
  reports must carry the category.
- The single-provider-advisory deployment mode acknowledges reality
  (some operators run one provider for cost reasons) without pretending
  the resulting review is a real red team.
- The trivial-rate ceiling closes module_01's flagged gap; the
  companion composer can no longer silently bypass G1 by producing
  a stream of trivial-composed suites.

## References

- ALM master spec `docs/RACT_v0.4.0_ANTILAZY_SPEC.md` §3.7 (G7),
  §3.8 (G8), §6 (companion provider constraint), §13 signals 7 and 8.
- ADR-0010 (acceptance predicates), ADR-0014 (closed action union),
  ADR-0016 (rootknot environment attestation), ADR-0019 (dual
  acceptance suite), ADR-0020 (patch differentiation + coverage
  delta), ADR-0021 (test integrity + under-edit).
- AdverTest (adversarial dual-agent framework, public paper).
- Bubblewrap (bwrap unprivileged sandboxing on Linux) — public
  repository `https://github.com/containers/bubblewrap`.
- macOS `sandbox-exec` (Seatbelt) — public Apple documentation.

RACT 0.4.0
