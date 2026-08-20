# ADR-0041 -- SubstrateLoop shim-wiring closure (SUBSTRATE §4-§7)

## Status

Accepted 2026-08-20. v0.5.1 module_05.

## Context

DeepSeek REVIEW_2 criticism 3 + REVIEW_3 arch-drift section:
``SubstrateLoop`` DECLARED an OS-enforced capability layer but
delegated most of the enforcement to whatever call-site convention
happened to be in force. The four concrete gaps the reviewers named:

1. Tool invocation had no chokepoint -- a call that bypassed the
   sandbox surface never generated a refusal event, never appeared
   in the invocation audit, and could ship a new tool without going
   through a gate at all.
2. Rollback ``SIGKILL`` reaped the parent process only; descendants
   spawned inside the step outlived the transaction boundary and
   held worktree file handles open (REVIEW_4_UNKNOWN §B3).
3. Sandbox init inherited the parent env wholesale under the
   non-bwrap code path; blacklist-based scrubbing missed any
   name-shaped-like-a-secret the operator had not enumerated
   (REVIEW_4_UNKNOWN §D1 data-exfil).
4. A commit that landed mid-loop could not be reverted past the
   commit -- worktree changes rolled but the branch already carried
   the sha, and no compensator was ever installed.

## Decision

Wire four subsystems and hoist them into ``SubstrateLoop``:

- **Tool-invocation gate** (``src/ract/executor/tool_gate.py``).
  ``ToolInvocationGate.invoke`` runs four gates in order --
  manifest declaration, registry implementation, args schema
  conformance, side-effect budget -- and emits
  ``tool.invocation.pre|post|refused`` events. Refusals raise
  ``ToolInvocationRefused`` (structured; carries ``tool_id``,
  ``gate``, ``reason``, ``details``). Wired at
  ``SubstrateLoop.invoke_tool``.
- **Process-group tree-kill** (``src/ract/executor/process_group.py``).
  ``spawn`` sets ``start_new_session=True`` (POSIX ``setsid``) or
  ``CREATE_NEW_PROCESS_GROUP`` + Job Object (Windows); ``kill_tree``
  reaps parent + every descendant via ``killpg(pgid, SIGKILL)`` or
  ``TerminateJobObject`` (with ``taskkill /F /T`` fallback).
  Idempotent; optional grace period sends SIGTERM first.
- **Environ allowlist** (``src/ract/security/sandbox_env.py``).
  ``build_sandbox_env`` computes a strict allowlist over
  ``manifest.env.passthrough ∪ .ract/sandbox_env.allowlist ∪
  DEFAULT_ALLOWLIST``, minus a hardcoded ``NEVER_PASSTHROUGH`` set
  (``AWS_*``, ``GITHUB_TOKEN``, ``OPENAI_API_KEY``, etc.). Names
  not on the union are dropped; only the COUNT lands in the WARN
  log (never the value or the name of the scrubbed var).
  ``UnenforcedSandbox.enter`` calls the loader so even the
  Windows stub emits a ``sandbox.granted`` event with the env
  audit.
- **Commit compensator** (``src/ract/executor/commit_compensator.py``).
  After each successful commit that advanced the loop's HEAD, the
  ``SubstrateLoop`` installs a ``CommitCompensator`` (soft-reset by
  default) onto the loop's ``CompensatorStack``. Loop disposal
  drives ``SubstrateLoop.dispose(success=)``; ``success=True`` (T1)
  discards the stack, otherwise the stack drains LIFO and each
  compensator ``reset --soft <sha_before>``s its branch.
  Compensators refuse to run against pushed commits
  (``check_pushed`` walks ``git branch -r --contains``); pushed
  compensators emit ``compensator.refused`` and leave the ref
  intact.

## Alternatives considered

**(a) Tool gate as a decorator around every tool.** Requires the
same discipline the previous shape asked for (author must remember
to decorate) and forfeits a single audit chokepoint. Rejected:
the whole point of the gate is that it is unavoidable.

**(b) Skip Job Object; ``taskkill /F /T`` alone.** ``taskkill``
walks the tree by PID at reap time; a race where a grandchild
spawns AFTER the walk but BEFORE the parent's PID slot is reclaimed
leaves a straggler. Job Object is a kernel-level bag; assignment
at spawn time closes the race. Rejected as sole strategy;
``taskkill`` kept as fallback when Job Object creation fails.

**(c) Env blacklist over ``os.environ``.** The status quo. Every
NEW enterprise secret shape shipped by the operator is an
implicit passthrough. Rejected: allowlist inverts the burden of
proof.

**(d) Hard reset on compensator drain (default ``mode="hard"``).**
Discards working-tree state too. A step that legitimately
produced artifacts we want to inspect post-mortem would lose them
under hard-default. Rejected: soft-reset default preserves
inspectability; ``mode="hard"`` remains a per-compensator opt-in.

**(e) Compensator runs on pushed commits via ``git push --force``.**
Rejected. The substrate boundary stops at ``git push``; force-
moving a remote ref is an operator ceremony, not a loop
compensator. The compensator emits ``compensator.refused`` on
pushed commits and lets the operator decide.

## Consequences

Positive:

- Every tool call in a substrate step now has a single audit
  chokepoint. New tools cannot ship without going through the
  gate.
- Rollback SIGKILL reaches parent + every descendant. The
  worktree teardown after rollback no longer trips on held file
  handles.
- Sandbox env is deny-by-default. A new enterprise secret shape
  shipped by an operator is invisible to the sandbox unless the
  manifest explicitly names it AND that name is not on
  ``NEVER_PASSTHROUGH``.
- Loop disposal on any T-cause other than T1 undoes every
  mid-loop commit that stayed local, so the run report can honestly
  claim "the tree is at the pre-loop state".

Negative:

- The tool registry MUST be populated before the loop enters step
  one; a loop constructed without a registry refuses every
  ``invoke_tool`` call at the ``registry`` gate. This is a
  migration surface -- existing call sites that go through
  ``Executor.execute`` still work (they do not call
  ``invoke_tool``); code paths that call the gate directly must
  wire the registry.
- Compensator install requires an extra ``git rev-parse HEAD``
  after each commit. Cheap (< 20 ms typical) but non-zero.

## Related

- SUBSTRATE spec §4 (Substrate Layer 3), §5 (Substrate Layer 4),
  §7 (Substrate Layer 6).
- REVIEW_2 criticism 3 (SubstrateLoop shim gaps).
- REVIEW_3 arch-drift section.
- REVIEW_4_UNKNOWN §B3 (SIGKILL to process group) + §D1
  (environ allowlist).
- ADR-0011 (worktree-per-step) -- the compensator sits above the
  worktree layer; a worktree rollback and a compensator drain are
  compatible (each covers a different transaction boundary).

## Flagged gaps (v0.6+)

- **Push-time compensator escalation.** Today, a pushed commit
  leaves the compensator refused; a v0.6 upgrade could open a
  handshake asking the operator to authorise ``git push --force``
  on the compensator's branch. Requires a signed handshake
  primitive that does not exist in the sacred spine today.
- **Tool budget per-scope escalation.** The gate's budget is
  per-step; a tool that legitimately needs 1000 invocations in
  one step (e.g. batch retrieval) must run outside the substrate
  or ship a `RequestHandshakeAction` for a wider budget. A v0.6
  scope could add a per-scope budget ladder.
- **Env allowlist Merkle attestation.** Today the allowlist file
  is trusted at read time; a v0.6 upgrade could compute a Merkle
  digest of the file's parse tree and stamp it into the Rootknot
  so a tampered allowlist trips RK verify.
- **``taskkill`` fallback race under ephemeral grandchildren.**
  When the Job Object creation refuses on Windows and we fall
  back to ``taskkill``, a grandchild spawned between the walk
  and the reap can leak. A v0.6 upgrade could wrap the fallback
  in a poll-until-no-descendants loop with a bounded retry.
- **Ed25519 sign of the tool registry snapshot.** The gate's
  declared-ids set is trusted at construction; an attacker who
  swaps the manifest between construction and first call could
  widen the gate silently. A v0.6 upgrade could hash the frozen
  registry and stamp the hash into the Rootknot.
