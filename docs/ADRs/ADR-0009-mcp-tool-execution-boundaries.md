# ADR-0009: MCP / Tool-Execution Boundaries

## Status

Accepted

## Context

RACT can invoke MCP tools and shell tools during a plan step to read context,
run commands, and mutate the workspace. These tools can touch the filesystem,
the network, and the shell — the same surfaces the threat model tiers T0–T3
govern (`src/ract/core/threat_model.py`). Without an execution boundary, a
compromised prompt or a misbehaving tool could perform a destructive action
(`rm -rf`, package publish, external shell) by routing it through a tool call
that bypasses the `authorize_action` gate that governs direct actions.

The architecture requires that *every* path to a workspace/network/shell
mutation passes through the same authorization gate, regardless of whether the
trigger is a direct action or a tool invocation.

## Decision

All MCP and tool invocations during a plan step pass through `authorize_action`
in `src/ract/core/threat_model.py`:

- **Tiering.** Each tool call is classified by `classify_action` into a
  `CapabilityTier` (T0 read, T1 workspace-write, T2 environment, T3 external)
  using the same rules as direct actions. The default policy applies:
  `ALLOW` (T0), `ALLOW_WITH_ROOTKNOT` (T1), `REQUIRE_HANDSHAKE` (T2),
  `REFUSE` (T3).
- **Argument validation.** Tool arguments are validated against the tool's
  declared schema before the call is dispatched. A tool whose arguments do not
  match its declared schema is refused; it is never called with best-effort
  coercion.
- **Destructive calls require handshake.** Any T2/T3 tool call is recorded in
  the `HandshakeRegistry` and deferred for operator approval (per ADR-0006).
  The loop continues with other work; the destructive call does not execute
  until approved.
- **Serial execution.** Tool calls within a step execute serially
  (see `docs/ARCHITECTURE.md`, "Concurrent tool execution"). There is no
  parallel tool dispatch, so authorization is evaluated per-call without
  concurrency on the gate.

## Consequences

- The authorization surface is uniform: there is no privileged back door
  through the tool layer.
- Tool authors must declare an accurate argument schema; an underspecified
  schema produces refused calls, which is the intended pressure.
- Destructive automation is impossible without a recorded operator handshake,
  even if a prompt injection attempts to route it through a tool.

## Alternatives Considered

- **Trust-all (call tools as requested).** Rejected. It would make the threat
  model advisory rather than enforceable and reintroduce the silent-failure
  modes the model exists to prevent.
- **Prompt-level filtering (ask the model not to call dangerous tools).**
  Rejected. Prompt instructions are not a security boundary; they are
  bypassable by adversarial input and offer no enforcement when bypassed.
- **Post-hoc logging only (let the call run, log it, review later).**
  Rejected. Logging a destructive action after it executed does not prevent
  it. The handshake gate exists precisely because some actions cannot be
  undone.

## References

- `src/ract/core/threat_model.py` (`authorize_action`, `classify_action`,
  `CapabilityTier`, `PolicyDecision`)
- `src/ract/mcp_adapter.py`
- `src/ract/handshake_registry.py`
- ADR-0004 (tool-execution threat model), ADR-0006 (deferred-approval
  handshakes)
