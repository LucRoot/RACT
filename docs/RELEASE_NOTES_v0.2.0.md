:warning: This file is project documentation, not part of the source code.

# RACT 0.2.0 Release Notes

## Summary

RACT 0.2.0 is the **Provenance and Invariants** release. It moves the project from a broad scaffold of CLI verbs to a claim-and-verify architecture: every artifact carries a signed `Rootknot`, every plan step declares assumptions with a four-state lifecycle, and the recursion loop halts on explicit, externally verifiable termination causes. The release also ships a published threat model, capability-based provider routing, and a reproducible eval harness.

This release directly addresses the depth-of-craft critique: fewer shallow competitive claims, more load-bearing invariants, and evidence committed in `evals/runs/`.

## What's New

### Signed provenance capabilities
- **`Rootknot`** in `src/ract/core/rootknot.py` — every artifact is bound to its plan step, assumption, generator, and parent artifacts.
- **ed25519 signatures** via `src/ract/core/keys.py` — each rootknot is signed by the generator session key.
- **`verify_workspace`** in `src/ract/core/provenance.py` — checks invariants RK-1 and RK-2 before every recursion step.

### Assumption-driven programming
- **`Assumed[T]`** and the assumption registry in `src/ract/core/assumption.py`.
- Four-state lifecycle: `proposed`, `active`, `discharged`, `violated`.
- Transitive violation propagation through the dependency graph.

### Formal loop termination
- Termination causes T1–T7 in `src/ract/core/loop.py`: completion, regression, provenance violation, assumption cascade, budget exhaustion, handshake block, and provider fault.
- `ProgressOracle` and `MilestoneOracle` are now scheduling heuristics; final authority rests on predicate evaluation.

### Threat model and guardrails
- Capability tiers T0–T3 with a published refuse-list.
- `SafetyGuardrail` and `Chesterton's Fence` wired into the executor.
- See `docs/THREAT_MODEL.md` and `docs/ADRs/ADR-0004-tool-execution-threat-model.md`.

### Capability-based provider routing
- `InferenceRouter` selects providers by capability hint and health.
- Presets for OpenAI, Anthropic, local HTTP, and internal adapters.

### Deferred-approval handshakes
- High-risk actions queue for async operator review instead of blocking the loop.
- `HandshakeRegistry` manages pending, approved, and rejected handshakes.

### Versioned plan schema
- `src/ract/core/schemas/plan-v1.json` with migration support.
- `PlanValidator` enforces the schema at the boundary.

### Eval harness
- Three reproducible tasks under `evals/tasks/`.
- Committed run reports in `evals/runs/`.
- `ract eval run` supports per-provider benchmarking.

### Docs and project hygiene
- README rewritten to a concise, technical pitch; author content moved to `AUTHOR.md`.
- CI badge and coverage badge added to README.
- Package renamed from `rootact` to `ract` everywhere.
- `Assumed[T]` vocabulary replaces the previous `Rooted[T]` naming.

## Quality metrics

| Metric | Value |
|---|---|
| Tests | 1079+ passed |
| Line coverage | 89% |
| `ruff check src tests scripts` | clean |
| `mypy src tests` | clean |
| Plan schema validation | enforced |
| Eval reports | committed |

## Known limitations

- MCP tools run serially within a plan step.
- Benchmark numbers are machine-specific; re-run on your hardware.
- Windows file-watcher tests can be flaky under heavy I/O.

## Installation

```bash
pip install ract==0.2.0
```

Or from source:

```bash
git clone https://github.com/LucRoot/RACT.git
cd RACT
git checkout v0.2.0
./scripts/install.sh --local --venv
```

## Verification

```bash
ract --version
ract doctor
ract config validate
ract provider health
```

## Migration from 0.1.x

- Update imports from `rootact` to `ract`.
- Replace `Rooted[T]` with `Assumed[T]`.
- The `_ROOT_KNOT` sentinel is retained as a legacy fallback through 0.2.0 and will be removed in 0.3.0.

<!-- RACT v0.2.0 - Provenance and Invariants -->
