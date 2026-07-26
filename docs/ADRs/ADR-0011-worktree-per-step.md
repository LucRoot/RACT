# ADR-0011: Worktree-per-Step + Container-per-Step as the Execution Substrate

## Status

Accepted

## Context

Through v0.3, RACT's executor wrote directly to the live workspace. Plans
were the durable artifact and each step's writes landed in the tree
alongside every other step's writes. Rollback was after-the-fact: a
failed step's post-hoc diff-undo, dependent on a synchronous provenance
tracker catching the write before the loop advanced.

The audit against `docs/RACT_v0.4.0_SUBSTRATE_SPEC.md` §11 signal 3
marked this MISSING for three reasons:

- **Crash consistency was bolted on last.** If the loop died mid-step,
  the workspace was in a partial state; the post-hoc undo path could not
  restore isolation between steps.
- **No commit boundary per step.** Two steps that touched the same file
  in the same iteration silently interleaved.
- **The handshake path was a plan-level acknowledgement, not a git-level
  block.** A high-risk step could commit its changes before the operator
  reviewed the handshake; approval was semantic only.

The SUBSTRATE spec §3 prescribes: every step opens a transaction,
isolation is enforced by the substrate, commit and rollback are
first-class, and a blocked handshake blocks the commit — not just the
next-step decision.

## Decision

Every step in the v0.4 loop opens a `StepTransaction`
(`src/ract/core/transaction.py`). Isolation is layered:

- **Code isolation** is a `git worktree` on a step-specific branch named
  `rootact/step/<step_id_hex>`, created off the loop's current parent
  snapshot (see the [git-worktree docs](https://git-scm.com/docs/git-worktree)).
  Worktrees share the object store, so the per-step cost is dominated by
  checkout, not by cloning. Branch naming is a discipline: every step
  branch matches the same prefix, so
  `git branch --list "rootact/step/*"` enumerates the active
  transactions.
- **Runtime isolation** is a container per worktree, opt-in per plan
  step. Two backends ship: `DaggerBackend` (delegates to the Dagger CLI;
  see the [Dagger Container Use README](https://github.com/dagger/container-use))
  and `PodmanBackend` (falls back to `docker` when `podman` is not on
  PATH). A step whose `runtime_image` is `None` runs in the worktree
  alone. Module_03 will land the OS-enforced sandbox
  (bwrap + Landlock + seccomp on Linux, Seatbelt on macOS) *inside* the
  container the shim starts; this module only commits to the container
  existing and mounting the worktree.
- **Handshake blocking at the git layer** replaces the v0.3 plan-level
  acknowledgement. `HandshakeRegistry.blocks_commit(handshake_ids)`
  returns the unresolved ids among a step's declared gates; a non-empty
  result forces `TransactionOutcome.BLOCKED_ON_HANDSHAKE`. The worktree
  stays intact for operator inspection, the parent-snapshot pointer does
  not advance, and dependent steps cannot commit past the blocked one.

The workflow-versus-activity split from the
[Temporal durable-execution model](https://docs.temporal.io/) informs the
shape: the loop describes what "done" means (the module_01 acceptance
suite); each transaction is an activity whose outcome
(`COMMITTED`, `ROLLED_BACK`, `BLOCKED_ON_HANDSHAKE`) is a recorded fact.

The plan reduces to a schedule over these transactions; the workspace
snapshot chain is the durable artifact.

## Rejected alternatives

- **Writes to the live tree with post-hoc rollback.** The v0.3 baseline.
  Crash consistency is added last (SUBSTRATE §3.1); a mid-iteration
  crash leaves a partial state that the rollback path cannot restore
  cleanly. Rejected.
- **Full clone per step.** Guaranteed isolation but wasteful — a
  hundred-step run clones the repo a hundred times. `git worktree` was
  designed for exactly this case (shared object store, cheap per-step
  checkout). Rejected.
- **Docker-only isolation, no worktree.** A container gives runtime
  isolation but the filesystem is still the shared workspace on the
  host. Two containers mutating the same tree race; there is no branch
  the operator can inspect after a rollback. Rejected.
- **Deferred handshake acknowledgement only (v0.3 pattern).** The
  operator eventually reviews the handshake, but by then the step has
  committed its writes and any dependent step has run against them.
  Rejected because it collapses the block to a plan-level flag rather
  than a git-level fence — SUBSTRATE §3.5's stated risk.

## Consequences

Positive:

- Every step's diff is inspectable via
  `git diff <parent_snapshot> rootact/step/<step_id>`; the v0.4 CLI
  `ract session diff <step_id>` wraps this.
- Rollback is a filesystem operation, not a semantic undo path. A rolled-
  back step's worktree and branch are gone; the auction test asserts no
  dangling `rootact/step/*` branch after a failed transaction.
- Loop-entry preconditions are cheap: refuse a non-git workspace with a
  specific error; refuse a workspace with uncommitted tracked changes
  and name the offending paths. (Lateral chain branch E; enforced in
  `src/ract/executor/worktree.py::ensure_git_repo` and
  `ensure_clean_tracked_tree`.)

Negative / follow-ups:

- `LoopController` accepts an `AcceptanceSuite` and, when set, routes
  through `build_loop_state`. The provider-facing step executor
  (`ract.executor.steps.Executor`) still writes directly to the live
  tree — the substrate loop (`ract.executor.loop.SubstrateLoop`) is a
  new primitive the CLI's live loop does not yet default to. That
  wiring is honest-gap flagged for module_03+.
- Long-lived `rootact/step/*` branches accumulate. Lateral chain branch
  C (`ract session gc`) is deferred; the naming discipline makes gc
  trivial when it lands.
- The container backend is a CLI-shaped shim (no `dagger-io` /
  `podman-py` SDK on RACT's dependency list) so the substrate stays
  importable on a machine without either runtime. Live container
  behavior is only observed when a plan step actually declares
  `runtime_image`.

## References

- `docs/RACT_v0.4.0_SUBSTRATE_SPEC.md` §3 (Substrate Layer 2:
  Transactional Execution) and §11 signal 3.
- git worktree public documentation: `https://git-scm.com/docs/git-worktree`
- Dagger Container Use README: `https://github.com/dagger/container-use`
- Claude Code subagents with `isolation: worktree` (Anthropic public
  documentation).
- Temporal durable-execution model:
  `https://docs.temporal.io/`
- OpenHands V1 SDK (native sandboxed execution; SUBSTRATE §3.2):
  `https://github.com/All-Hands-AI/OpenHands`
- v0.3 `HandshakeRegistry` (source: `src/ract/handshake_registry.py`) as
  the pre-substrate baseline that this ADR extends.

<!-- RACT 0.4.0 -->
