# RACT (Root Agentic Coding Tool)

![RACT CI](https://github.com/LucRoot/RACT/actions/workflows/ci.yml/badge.svg)
![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/LucRoot/RACT/main/docs/coverage-badge.json)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![Version](https://img.shields.io/badge/version-0.5.0-blue)

RACT is a model-agnostic, local-first agentic coding tool built around three ideas: signed provenance capabilities (*rootknots*) on every artifact, explicit assumptions for every plan step, and milestone-halting recursion instead of fixed iteration counts.

## What v0.5.0 changes

v0.5.0 is the Memory Discipline minor release. It installs a new
memory substrate on top of v0.4.1 without touching the sacred spine
(Rootknot three-signature schema, AL-1, author-name-free tree). The
pipeline (`_BUILD/ract_v0.5.0_memory_discipline/`) delivered nine
substrate modules plus a release-close module:

- **Token budget accountant** with hard-ceiling refusal per function
  and composition override (`src/ract/memory/budget.py`).
- **Three query indexes** — the symbol index (tree-sitter + SQLite +
  FTS5), the graph index (LSP-populated call/type edges), and the
  semantic index (LanceDB + `bge-small-en-v1.5`). An incremental file
  watcher keeps them current.
- **Retrieve primitive** with a four-level cascade (symbol → graph →
  semantic → best-effort), a query cache keyed on
  `(query_hash, repo_commit_hash)`, and four chunk formats.
- **Four function contracts** — `intake`, `research`, `plan`, `edit`
  — each with a typed contract, a v1 prompt, and a paired test file.
- **Four playbooks** — `refactor_rename`, `refactor_extract`,
  `bug_fix`, `unit_test` — composed of those four functions.
- **Three self-adjustment probes** — `needle`, `coherence`,
  `adherence` — writing a per-repo capability fingerprint to
  `.rack/probes/capability.json`.
- **Integration wiring.** `SubstrateLoop` reads a retrieval bundle
  off `SubstrateStepSpec.metadata`; `Rootknot` payload carries an
  optional `retrieval_attestation`; seven new EventKind members;
  three new CLI subverbs (`ract memory init`,
  `ract memory apply-narrowings`, `ract retrieval query`).

Verify: `pytest -q tests/test_release_surface.py` runs the 56-signal
sweep (11 REBUILD + 16 SUBSTRATE + 16 ALM + 13 MEMORY) plus the
memory-module surface check plus the closed-IP wordlist gate. See
`CHANGELOG.md` `[0.5.0]` for the exhaustive change list and
`docs/ROADMAP.md` for v0.6 hardening backlog (deferred polish).

## What v0.4.1 changes

v0.4.1 is the Intent-Fidelity patch release. No new features and no
breaking changes. The pipeline
(`_BUILD/ract_v0.4.1_intent_fidelity/`) walked seven prior eras (v0.1.x,
v0.2.0, v0.3.0, v0.4.0 SUBSTRATE, v0.4.0 ALM, v0.4.0-rc1 audits,
restoration clusters 1+2) and verified each era's stated intent still
holds as actual tree behavior. Drift became fix commits with regression
tests; unresolvable drift became a `docs/ROADMAP.md` entry.

Verify: `pytest -q tests/test_release_surface.py` runs the 43-signal
sweep (11 REBUILD + 16 SUBSTRATE + 16 ALM) plus per-module attestations
plus the closed-IP wordlist gate. See `CHANGELOG.md` `[0.4.1]`.

## What v0.4.0 landed

v0.4.0 was the first release where **the environment decides**, not the
model. Substrate: every plan step runs in its own git worktree under an
OS-enforced sandbox derived from a `CapabilityManifest`; every model
action is a member of a closed Pydantic union; every run emits a
hash-chained event log at `evals/runs/<run_id>/events.jsonl` and
optionally OpenTelemetry spans; termination T1 reads: every required
predicate in the `AcceptanceSuite` evaluates true against the final
snapshot (the model does not say "done"). Rootknot gained
`environment_signature` (**Invariant RK-3**). ALM: eight pre-commit
gates (G1-G8), a sycophancy circuit, an Investigator, and a third
Rootknot signature (`antilazy_signature`) held by a separate key
(**Invariant AL-1**). See `CHANGELOG.md` `[0.4.0]` for the exhaustive
change list; see `docs/ROADMAP.md` for the v0.5 hardening backlog.

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
ract memory init                     # build the three memory-discipline indexes for this repo
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
- `ract session ls` — list persisted transactional sessions (v0.4 substrate).
- `ract session diff <step_id>` — show the diff a step's `StepTransaction` applied (v0.4 substrate).
- `ract plan diff` — show the diff a plan would apply.
- `ract run` — execute an intent against the workspace.
- `ract fence inspect --file <path>` — inspect threat-model guardrails.
- `ract conformance run --provider <name>` — run the per-provider conformance corpus (schema + tool discipline + refusal fidelity + anti-lazy). Router gates registration on a recent passing report.
- `ract trace replay <run>` — replay a hash-chained event log against the current tree (emits determinism warning on HEAD mismatch).
- `ract trace fork <run> <event_id>` — fork a trace from a specific event.
- `ract trace diff <run_a> <run_b>` — diff two traces event-by-event.
- `ract trace to-test <run>` — materialize the trace's provider prompts and responses as pinned test fixtures.
- `ract provenance verify <path>` — verify a file's `Rootknot` (RK-1 + RK-2 always; RK-3 when the sidecar is v2+; AL-1 when the sidecar is v3 and the workspace is in strict mode).
- `ract plan analyze <session>` — print the `PlanRiskReport` advisory for a session (restoration cluster 2; reads the `plan.risk_assessed` event out of `events.jsonl`).
- `ract memory init` — build the symbol / graph / semantic indexes for the current workspace under `.rack/index/` (v0.5.0 memory discipline).
- `ract memory apply-narrowings` — apply queued budget-narrowings from the failure record store (v0.5.0 memory discipline).
- `ract retrieval query <text>` — issue a retrieval query against the memory-discipline three-index cascade (v0.5.0; skeleton — full CLI wiring queued for v0.6).

Anti-lazy gates (G1-G8) are pre-commit helpers rather than top-level CLI verbs.
A run's `evals/runs/<run_id>/` directory gains one report per gate:
`mutation_kill.json`, `patch_diff.json`, `coverage_delta.json`,
`test_integrity.json`, `under_edit.json`, `companion_report.json`,
`effort_reconciliation.json`, `sycophancy.json`, `investigator.json`, and (for
rule-like intents) `iso_perturb.json`.

## What makes RACT different

- **Provenance-anchored artifacts** — every file the loop writes carries a signed `Rootknot` binding it to its plan step, assumption, generator, and parent artifacts. See [`docs/PROVENANCE.md`](docs/PROVENANCE.md).
- **Assumption-driven programming** — assumptions live in a registry with a four-state lifecycle (`proposed`, `active`, `discharged`, `violated`); violations propagate through the dependency graph.
- **Milestone-halting recursion** — the loop halts on completion, regression, provenance violation, assumption cascade, budget exhaustion, handshake block, or provider fault, each with a distinct termination cause. On a refactoring task this spends measurably fewer tokens than a naive fixed-iteration loop — see [`evals/benchmarks/refactor-token-usage/report.md`](evals/benchmarks/refactor-token-usage/report.md).
- **Operator Handshake** — high-risk actions queue for async review instead of blocking the loop.

## Architecture

Core modules live in `src/ract/core/`: `rootknot.py` (signed provenance), `assumption.py` (`Assumed[T]` registry), `plan.py` (schema + validator), `loop.py` (T1–T7 recursion). See `docs/ARCHITECTURE.md` for the system diagram, boundary contracts, and failure modes; `docs/ADRs/` for decision records.

## Evals & Benchmark

Three reproducible tasks under `evals/tasks/` (reports in `evals/runs/`). See [`evals/README.md`](evals/README.md) for the eval-tree tour. `evals/benchmarks/refactor-token-usage/` compares the milestone-driven loop against a naive baseline on tokens-to-pass; reproduce with `python evals/benchmarks/refactor-token-usage/report.py`.

## Verify

```bash
ract doctor                              # workspace health + dependencies
ract provenance verify src/hello.py      # check a file's Rootknot (RK-1 + RK-2 + RK-3 + AL-1)
ract conformance run --provider fake     # run the per-provider conformance corpus
ract trace replay evals/runs/<run_id>    # replay a hash-chained event log
pytest -q                                # full suite (includes tests/test_release_surface.py)
```

The full release-surface sweep is `pytest -q tests/test_release_surface.py`
(56 signals: 11 REBUILD + 16 SUBSTRATE + 16 ALM + 13 MEMORY, plus the
memory-module surface check + the closed-IP wordlist gate).

RACT v0.5.0 enforces four invariants at verify time (unchanged from v0.4.1):

- **RK-1 (Author Attestation, v0.2).** `Rootknot.generator_signature` verifies
  under the resolved generator pubkey.
- **RK-2 (Sidecar Integrity, v0.2).** The sidecar's Merkle root binds every
  attested field.
- **RK-3 (Environmental Attestation, v0.4 substrate).** The sandbox-key
  `environment_signature` verifies; `acceptance_suite_digest`,
  `predicate_results`, and `manifest_digest` are all registered.
- **AL-1 (Anti-Lazy Attestation, v0.4 ALM).** The ALM-verifier
  `antilazy_signature` verifies; every `GateResult` is PASS (or its
  handshake was approved); `reversal_taint` is `clean` (or the run is on
  the operator's `accepted_partial_taint_runs` set). `strict=True` refuses
  any sidecar older than v3.

See `evals/LEADERBOARD.md` (which now carries a per-provider
`attested_pass_rate` column) and `evals/conformance/COMPANION_MATRIX.md`
(eligible primary-companion provider pairs).

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

<!-- RACT 0.5.0 -->
