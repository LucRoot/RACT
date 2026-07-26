:warning: This file is project documentation, not part of the source code.

# RACT Architecture

RACT is a model-agnostic, local-first agentic coding tool. It turns operator intent into structured plans, executes those plans through configurable providers, and writes verified artifacts to disk.

## System diagram

```
┌─────────────┐     intent      ┌─────────────┐     plan        ┌───────────┐
│   Operator  │ ───────────────▶ │   Planner   │ ─────────────▶ │  Manager  │
└─────────────┘                  └─────────────┘                └─────┬─────┘
       ▲                                                              │
       │                         ┌─────────────┐                      │
       │      run report         │   Executor  │ ◀────────────────────┘
       │ ◀────────────────────── │ (chokepoint)│
       │                         └──────┬──────┘
       │                                │ writes
       │                         ┌──────┴──────┐
       │                         │  Workspace  │
       │                         │ + Rootknot  │
       │                         │   index     │
       │                         └─────────────┘
```

The planner emits a versioned plan. The manager recurses through steps. The executor is the only component allowed to mutate the workspace. Every written artifact is entered into the Rootknot index.

## Boundaries and contracts

1. **Plan contract.** Every `Plan` carries a schema version, a load-bearing assumption, and an ordered list of steps. The plan validator rejects unknown schema versions and steps with missing required fields.
2. **Provenance contract.** Every written artifact carries a signed `Rootknot` that binds it to its plan step, assumption, generator, and parent artifacts. `verify_workspace` checks RK-1 and RK-2 before each recursion step. The public statement of what a Rootknot attests and how RACT stays independent of private systems lives in [`docs/PROVENANCE.md`](PROVENANCE.md).
3. **Assumption contract.** Every step declares the assumptions it depends on. The `AssumptionRegistry` tracks the lifecycle (`proposed`, `active`, `discharged`, `violated`) and propagates violations through the dependency graph.
4. **Threat-model contract.** Every workspace-mutating action passes through `authorize_action` in `src/ract/core/threat_model.py`. Tier-3 actions are refused by default; tier-2 actions require an operator handshake.
5. **Termination contract.** The recursion loop halts on one of T1–T7, each with a distinct `TerminationCause`: success, regression, provenance violation, assumption cascade, budget exhaustion, handshake block, or provider fault.

## Verification

- Core invariants are exercised by property tests in `tests/property/`.
- The eval harness runs three reproducible tasks under `evals/tasks/` and writes reports to `evals/runs/`.
- CI runs lint, type-check, tests, and eval-smoke on every push.

<!-- RACT 0.2.0 -->
