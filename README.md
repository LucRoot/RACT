# RACT (Root Agentic Coding Tool)

![RACT CI](https://github.com/LucRoot/RACT/actions/workflows/ci.yml/badge.svg)
![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/LucRoot/RACT/main/docs/coverage-badge.json)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![Version](https://img.shields.io/badge/version-0.3.0-blue)

RACT is a model-agnostic, local-first agentic coding tool built around three ideas: signed provenance capabilities (*rootknots*) on every artifact, explicit assumptions for every plan step, and milestone-halting recursion instead of fixed iteration counts.

## Install

```bash
pip install ract
```

Or from source:

```bash
git clone https://github.com/LucRoot/RACT.git RACT
cd RACT
./scripts/install.sh --local --venv
```

See [`docs/QUICKSTART.md`](docs/QUICKSTART.md) for a step-by-step tutorial.

## Quickstart

```bash
ract init --template python-package --provider local
ract doctor                          # verify workspace and dependencies
ract fence inspect --file src/hello.py  # check safety guardrails and threat-model boundaries
ract run "add a test for the hello-world script" --config ract.yaml --dry-run
ract run "add a test for the hello-world script" --config ract.yaml
ract run "refactor the greeting module" --config ract.yaml --loop --max-iterations 5
```

## CLI Verb Index

- `ract doctor` — verify workspace health and dependencies.
- `ract config validate` — validate ract.yaml configuration.
- `ract provider health` — check configured provider reachability.
- `ract session list` — list persisted run sessions.
- `ract plan diff` — show the diff a plan would apply.
- `ract run` — execute an intent against the workspace.
- `ract fence inspect --file <path>` — inspect threat-model guardrails.

## What makes RACT different

- **Provenance-anchored artifacts** — every file the loop writes carries a signed `Rootknot` binding it to its plan step, assumption, generator, and parent artifacts. See [`docs/PROVENANCE.md`](docs/PROVENANCE.md).
- **Assumption-driven programming** — assumptions live in a registry with a four-state lifecycle (`proposed`, `active`, `discharged`, `violated`); violations propagate through the dependency graph.
- **Milestone-halting recursion** — the loop halts on completion, regression, provenance violation, assumption cascade, budget exhaustion, handshake block, or provider fault, each with a distinct termination cause. On a refactoring task this spends measurably fewer tokens than a naive fixed-iteration loop — see [`evals/benchmarks/refactor-token-usage/report.md`](evals/benchmarks/refactor-token-usage/report.md).
- **Operator Handshake** — high-risk actions queue for async review instead of blocking the loop.

## Architecture

Core modules live in `src/ract/core/`: `rootknot.py` (signed provenance), `assumption.py` (`Assumed[T]` registry), `plan.py` (schema + validator), `loop.py` (T1–T7 recursion). See `docs/ARCHITECTURE.md` for the system diagram, boundary contracts, and failure modes; `docs/ADRs/` for decision records.

## Evals & Benchmark

Three reproducible tasks under `evals/tasks/` (reports in `evals/runs/`). `evals/benchmarks/refactor-token-usage/` compares the milestone-driven loop against a naive baseline on tokens-to-pass; reproduce with `python evals/benchmarks/refactor-token-usage/report.py`.

## Verify

```bash
ract doctor                              # workspace health + dependencies
ract provenance verify src/hello.py      # check a file's Rootknot (valid/invalid)
pytest -q                                # full suite
```

## License

PolyForm Noncommercial License 1.0.0 — free for personal use, research, education, and noncommercial organizations; commercial use requires an agreement. See [`COMMERCIAL.md`](COMMERCIAL.md) and [`AUTHOR.md`](AUTHOR.md).

## Known limitations

- Windows file-watcher tests can be flaky under heavy I/O.
- MCP tools run serially within a plan step.
- Benchmark numbers are machine-specific; re-run on your hardware.

---

License: PolyForm Noncommercial 1.0.0. Measurements: take them as one data point from one machine on one day, and re-run on yours.

---

**Author:** Dr. Lucas Root, Ph.D. — [info@lucasroot.com](mailto:info@lucasroot.com)

<!-- RACT 0.2.0 -->
