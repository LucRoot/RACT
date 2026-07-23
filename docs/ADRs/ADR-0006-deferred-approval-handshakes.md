# ADR-0006: Deferred-Approval Handshakes

## Status

Accepted

## Context

High-risk actions (deployments, package publishes, destructive commands) cannot be left to an autonomous loop, but blocking the loop for every approval kills throughput. The loop needs a way to flag risky actions, continue with safe work, and let the operator approve or reject them asynchronously.

## Decision

Introduce a `HandshakeRegistry` that persists pending approvals to disk. When the `MilestoneOracle` or threat-model tier check identifies a high-risk or Tier-2/Tier-3 action, the loop records a handshake and continues. The operator reviews the handshake list later and approves, rejects, or defers each item.

Handshakes are non-blocking by default. A milestone can be marked blocking only when the operator explicitly sets a blocking flag; in that case the loop halts with termination cause T6.

## Consequences

- The loop keeps moving while risky actions wait for human review.
- Approval state survives process restarts because it is stored in `.ract/handshakes.json`.
- The run report lists all pending handshakes so nothing is silently skipped.

## Alternatives Considered

- **Blocking approvals:** rejected. Waiting for operator input on every high-risk action would make the loop unusable for long-running tasks.
- **Full autonomy on Tier 3:** rejected. It would allow a compromised model or prompt injection to publish packages or delete resources without oversight.

## References

- `src/ract/handshake_registry.py`
- `src/ract/milestone_oracle.py`
