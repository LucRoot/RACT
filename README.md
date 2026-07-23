# RACT (Root Agentic Coding Tool)

![RootAct CI](https://github.com/LucRoot/RACT/actions/workflows/ci.yml/badge.svg)
![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/LucRoot/RACT/main/docs/coverage-badge.json)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)

RACT is a model-agnostic, local-first agentic coding tool built around three ideas: every artifact carries a signed provenance capability (a *rootknot*), every plan step is tied to an explicit assumption, and the recursion loop halts on measurable milestones rather than a fixed iteration count.

## Install

```bash
pip install rootact
```

Or from source:

```bash
git clone https://github.com/LucRoot/RACT.git RACT
cd RACT
./scripts/install.sh --local --venv
```

## Quickstart

```bash
rootact init --template python-package --provider local
rootact "add a test for the hello-world script" --config rootact.yaml --dry-run
rootact "add a test for the hello-world script" --config rootact.yaml
rootact "refactor the greeting module" --config rootact.yaml --loop --max-iterations 5
```

## What makes RACT different

- **Provenance-anchored artifacts** — every file the loop writes is bound to a `Rootknot` that records the plan step, assumption, generator, and parent artifacts, and can be cryptographically verified.
- **Assumption-driven programming** — assumptions live in a registry with a four-state lifecycle (`proposed`, `active`, `discharged`, `violated`); violations propagate through the dependency graph and trigger targeted re-planning.
- **Milestone-halting recursion** — the loop stops on completion, regression, provenance violation, assumption cascade, budget exhaustion, handshake block, or provider fault, each with a distinct termination cause.
- **Operator Handshake** — high-risk actions queue for async review instead of blocking the loop.

## Architecture

- `src/rootact/core/rootknot.py` — signed provenance capability.
- `src/rootact/core/assumption.py` — `Assumed[T]` and the assumption registry.
- `src/rootact/core/plan.py` — plan schema and validator.
- `src/rootact/core/loop.py` — recursion loop with invariants.

See `docs/ARCHITECTURE.md` for the system diagram and boundary contracts, and `docs/ADRs/` for the architectural decision records.

## Evals

Three reproducible tasks live under `evals/tasks/`. Run reports are committed to `evals/runs/`. See `evals/README.md`.

## License

RACT is licensed under the **PolyForm Noncommercial License 1.0.0** — free for personal use, research, education, and noncommercial organizations. Commercial use requires a separate agreement. See [`COMMERCIAL.md`](COMMERCIAL.md).

See [`AUTHOR.md`](AUTHOR.md) for project authorship and background.

<!-- RACT 0.2.0 -->
