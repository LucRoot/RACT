# ADR-0004: Tool Execution Threat Model

## Status

Accepted

## Context

RACT executes plans produced by a language model. A plan can ask the executor to write files, run shell commands, install packages, push commits, or call MCP tools. Without an explicit boundary, the system defaults to "trust the model," which is unsafe for an agent that runs unattended in a user's workspace.

The boundary must be:

- deterministic: the same plan always receives the same authorization decision,
- auditable: every refused action leaves a structured record,
- ergonomic: legitimate coding work (file writes, test runs) stays frictionless,
- conservative: dangerous operations require explicit operator approval.

## Decision

Introduce a capability-tier model with four tiers and a per-action authorization check.

| Tier | Name | Default policy |
|------|------|----------------|
| T0 | Read-only | Allow |
| T1 | Workspace-write | Allow with Rootknot |
| T2 | Environment | Require operator handshake |
| T3 | External | Refuse by default |

Classification is based on schema fields, not natural-language parsing, so it is deterministic. The executor runs `authorize_action(step)` before dispatching any step, including MCP `tool_call` steps, making the executor the single chokepoint for every workspace-mutating action.

T1 writes are constrained to the workspace root. T2 actions queue an operator handshake and continue only after approval. T3 actions are refused unless the session opted in with `--allow-tier-3`, and each T3 action still requires a handshake.

## Consequences

- Every workspace mutation passes through one authorization function.
- Adversarial plans that escape to shell, publish packages, or delete files are blocked before execution.
- The run report carries a `refusals` list for post-hoc review.
- Legitimate file writes require only a Rootknot, so normal coding loops are not slowed by prompts.

## Alternatives Considered

- **Unconstrained shell:** rejected. It would let a compromised model prompt or a prompt-injection attack execute arbitrary code.
- **Docker per step:** rejected. Cold-start latency and filesystem overhead make it too slow for an inner-loop coding assistant.
- **Pure static analysis of plan actions:** rejected. It misses runtime arguments and MCP tool payloads; the check must happen at dispatch time.

## References

- `src/rootact/core/threat_model.py`
- `docs/THREAT_MODEL.md`
- `tests/security/test_refuse_list.py`
