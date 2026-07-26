# ADR-0017 — Whisperer, Fence, and Auction as environment-enforced contracts

## Status

Accepted (v0.4.0, module_06).

## Context

v0.3 shipped Whisperer, Fence, and Auction as CLI features
(``src/ract/legacy_whisperer.py``, ``src/ract/chestertons_fence.py``,
``src/ract/dead_code_auction.py``). Each was invoked by the operator
on demand and returned a report. The mechanisms worked as diagnostics
but had no force in the loop: the planner did not have to consult the
Whisperer before proposing code, a delete action did not have to pass
through the Fence, and no scheduled sweep ran the Auction between
iterations.

SUBSTRATE spec §8 reframes all three as **contracts the environment
enforces, not features the model can opt out of**. Their load-bearing
scan / graph / blame logic is well-tested; the change is where and how
they are called.

## Decision

Ship a new ``src/ract/contracts/`` package with three primitives:

1. ``WhispererContract`` — runs before every planner call and injects
   a ``DialectBrief`` into the prompt template. The planner prompt
   surface pipes its intent through ``inject_into_prompt``; the model
   never sees the pre-injection form. Briefs are cached per workspace
   snapshot (lateral chain branch D).

2. ``FenceGate`` — intercepts every ``DeleteFileAction`` before the
   transaction opens. ``StepTransaction.open_transaction`` refuses a
   delete action whose ``fence_ticket_id`` is not present in
   ``FenceGate.approved_tickets``. Ticket minting only happens through
   ``FenceGate.evaluate``; the model cannot bypass. A bypass-attempt
   test constructs an unfenced delete and asserts refusal.

3. ``AuctionSweep`` — runs between the loop's iterations on the
   environment's schedule (gated by ``min_iteration_wall_seconds``).
   Each candidate is emitted as an ``auction.proposal`` event (a new
   entry in the closed ``EventKind`` vocabulary; see
   ``docs/EVENTS.md``) and staged for operator sign-off. Nothing is
   deleted without a handshake.

The v0.3 CLI wrappers (``ract whisper``, ``ract fence``,
``ract auction``) are preserved as convenience surfaces; they call
into the same scan primitives (``LegacyWhisperer``,
``ChestertonsFence``, ``DeadCodeAuction``) that the new contracts
consume. The environment-enforced path is the load-bearing one; the
CLI verbs are secondary tools that share the same core logic.

## Rejected alternatives

1. **Leave Whisperer / Fence / Auction as CLI features only.**
   Rejected — SUBSTRATE §8 shows that a diagnostic the model can
   ignore is not a contract. Model-authored code drifting from the
   codebase's conventions is common; a Whisperer the model never
   consults produces no lift.
2. **Replace the CLI wrappers with the contracts.** Rejected — the
   CLI verbs exist because the operator sometimes wants the report
   on demand (post-hoc review, one-off audit). Deleting them without
   a replacement burns operator workflow.
3. **Auction runs on model request.** Rejected — the whole point is
   to make deletion incentive external. A model asking for
   "housekeeping" is subject to the same incentive to keep the
   codebase small that led to hoarding in the first place.

## Consequences

- ``FenceGate`` composes with ``AuctionSweep`` — an Auction proposal
  the operator approves still becomes a ``DeleteFileAction`` that
  passes through ``FenceGate`` at execute time. Lateral chain branch
  E documents this explicitly.
- ``auction.proposal`` was added to the closed ``EventKind`` set in
  ``ract.trace.events``; ``docs/EVENTS.md`` needs a schema-version
  bump note for the addition (module_06 Flagged gaps).
- The Whisperer contract adds tokens to every planner prompt. The
  per-snapshot cache keeps the extra cost bounded to one build per
  workspace state.

## Reference sources

- SUBSTRATE spec §8 (Whisperer, Fence, and Auction as Contracts).
- v0.3 sources:
  ``src/ract/legacy_whisperer.py``,
  ``src/ract/chestertons_fence.py``,
  ``src/ract/dead_code_auction.py``.

<!-- RACT 0.4.0 -->
