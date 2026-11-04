# RACT (Root Agentic Coding Tool)

![RACT CI](https://github.com/LucRoot/RACT/actions/workflows/ci.yml/badge.svg)
![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/LucRoot/RACT/main/docs/coverage-badge.json)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![Version](https://img.shields.io/badge/version-0.6.0-blue)

RACT is a model-agnostic, local-first agentic coding tool built around three ideas: signed provenance capabilities (*rootknots*) on every artifact (see `docs/PROVENANCE.md`), explicit assumptions for every plan step, and milestone-halting recursion instead of fixed iteration counts.

## What v0.5.2 changes

v0.5.2 is the Deep-Audit Hardening release. Six modules layered on
v0.5.1 close fifteen paired Ox-Alpha-partnered deep-audit findings
without breaking wire compatibility. Highlights:

- **Rootknot v4 signature hardening**: `Rootknot.__post_init__` v4
  gate + authoritative verifier v4-label check +
  `min_acceptable_schema_version` policy + closed known-versions
  allowlist (`--min-schema=N` CLI flag).
- **Sandbox env library-injection defense**: 40+ new env vars added
  to NEVER_PASSTHROUGH (LD_PRELOAD, DYLD_INSERT_LIBRARIES, PYTHONPATH,
  NODE_OPTIONS, BASH_ENV, GLIBC_TUNABLES, GIT_SSH_COMMAND,
  HTTPS_PROXY, more).
- **Subagent lifecycle + PID-reuse hardening**: spawn-time
  `creation_time_ns` capture, tri-state PID identity check.
- **Run_id continuity**: new `write_sidecar_header` primitive +
  `RACT_RUN_ID` env plumbing across subprocess subagents.
- **Trace log durability + honest verify**: per-run
  `{run_id}.verify.json` warm-verify sidecar + streaming
  `iter_events` + torn-tail UTF-8 replace. New CLI verb
  `ract trace verify` (warm/cold, `--json`).
- **Memory system polish**: honest dataclass grouping docstring +
  on_moved reorder-race defense + new CLI verb
  `ract memory verify-consistency`.

Full change list: [CHANGELOG.md](./CHANGELOG.md#052---2026-08-22--deep-audit-hardening).
Migration walk-through: [docs/UPGRADING.md](./docs/UPGRADING.md).
Deferred backlog: [docs/RACT_v0.6_BACKLOG.md](./docs/RACT_v0.6_BACKLOG.md).

## What v0.5.1 changes

v0.5.1 is the External Review Response patch release. It closes the
trust-chain gap external review (DeepSeek + REVIEW_4_UNKNOWN) surfaced
against v0.5.0 without touching the sacred spine (Rootknot three-
signature schema, AL-1, author-name-free tree). The pipeline
(`_BUILD/ract_v0.5.1_external_review_response/`) delivered nine
closure modules plus release close:

- **RootknotWAL crash-consistency (G1)**: WAL-durable assumption
  replay (`src/ract/core/assumptions_wal.py`).
- **Rootknot canonical-bytes extension (G2 + G3)**: opt-in
  `workspace_digest` + `prompt_digest` + `run_id`; schema_version
  3 → 4; v3 sidecars still verify.
- **RFC 8785 JCS**: `src/ract/canonical.py` `dumps_jcs` +
  15-file migration; grep-gate at
  `tests/architecture/test_no_sort_keys_in_canonical_paths.py`.
- **T8 PROMPT_DRIFT + T9 PROMPT_DIGEST_MISSING + `intent recompile`**, 
  per-iteration drift hook; HMAC-signed recompile via `.ract/operator.key`
  OR `RACT_OPERATOR_KEY`.
- **SubstrateLoop shim closure**: four-gate `ToolInvocationGate`,
  process-group tree-kill, environ allowlist, git-commit compensator.
- **Ambient run_id ContextVar**: `src/ract/runtime.py`;
  `LoopController.run()` binds at entry.
- **Historical Manifest Ledger**: append-only Merkle-chained JSONL
  + content-addressable snapshot store.
- **Polyglot G5/G6 via tree-sitter**: dead-code + test-copy-paste
  detectors for Python + JS + TS + Rust + Go.
- **Sycophancy classifier v2**: AST-delta + WhispererContract event;
  F1 = 1.000.

See `CHANGELOG.md` `[0.5.1]` and `docs/ROADMAP.md` for v0.6 hardening.

## What v0.5.0 changes

v0.5.0 is the Memory Discipline minor release. It installs a new
memory substrate on top of v0.4.1 without touching the sacred spine
(Rootknot three-signature schema, AL-1, author-name-free tree). The
pipeline (`_BUILD/ract_v0.5.0_memory_discipline/`) delivered nine
substrate modules plus a release-close module:

- **Token budget accountant** with hard-ceiling refusal per function
  and composition override (`src/ract/memory/budget.py`).
- **Three query indexes**: the symbol index (tree-sitter + SQLite +
  FTS5), the graph index (LSP-populated call/type edges), and the
  semantic index (LanceDB + `bge-small-en-v1.5`). An incremental file
  watcher keeps them current.
- **Retrieve primitive** with a four-level cascade (symbol → graph →
  semantic → best-effort), a query cache keyed on
  `(query_hash, repo_commit_hash)`, and four chunk formats.
- **Four function contracts**: `intake`, `research`, `plan`, `edit`
each with a typed contract, a v1 prompt, and a paired test file.
- **Four playbooks**: `refactor_rename`, `refactor_extract`,
  `bug_fix`, `unit_test`, composed of those four functions.
- **Three self-adjustment probes**: `needle`, `coherence`,
  `adherence`, writing a per-repo capability fingerprint to
  `.ract/probes/capability.json`.
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

Earlier releases: see [CHANGELOG.md](CHANGELOG.md).

## What v0.4.0 landed

v0.4.0 was the first release where **the environment decides**, not the
model. Substrate: every plan step runs in its own git worktree under an
sandbox described by a `CapabilityManifest` (designed; in this build only
tier-3 commands on Linux run inside bubblewrap, after a self-test, and
`ract doctor --sandbox` shows what is enforced on your machine); every model
action is a member of a closed Pydantic union; every run emits a
hash-chained event log at `evals/runs/<run_id>/events.jsonl` (designed
in v0.4.0; the writer is not wired in this build, so a run records its
audit trail in the egress ledger, the signed sidecars, the rootknot
store and, on request, the session events from `--output-format
stream-json`) and optionally OpenTelemetry spans; termination T1 reads: every required
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
source .venv/bin/activate      # Linux and macOS; on Windows: .venv\Scriptsctivate
```

See [`docs/QUICKSTART.md`](docs/QUICKSTART.md) for a step-by-step tutorial.

## Quickstart

In the directory you want to work in, run:

```bash
ract setup
```

Setup finds a model server already running, or suggests a local model that
fits your machine (it never downloads) or a cloud provider (it never asks
for the key). It writes `ract.yaml` and checks it with one request. Bare
`ract` offers it too; see `docs/QUICKSTART.md`.

In a repository you cloned, RACT first lists any commands the repository
asks it to run (hooks, MCP servers, test gates) and runs them only if you
say so; `ract trust` records the decision until those files change.

Run `ract` with no arguments to work inside an interactive session (`/plan`, `/loop`,
`/doctor`, `/set`, and every verb as a slash command). The commands below work one at a
time from the shell.

```bash
ract init --template python-package --provider local
ract memory init                     # build the three memory-discipline indexes for this repo
ract doctor                          # verify workspace and dependencies
ract fence inspect --file src/<package>/__init__.py  # check safety guardrails; use any file in your project
ract run "add a test for the hello-world script" --config ract.yaml --dry-run
ract run "add a test for the hello-world script" --config ract.yaml
ract run "refactor the greeting module" --config ract.yaml --loop --yolo --max-iterations 5
```

Indexes need `RACT_EMBED_MODEL_ROOT` or `RACT_EMBED_ONLINE=1`.

Novelty budget and memory index notes: [docs/NOVELTY_AND_MEMORY.md](docs/NOVELTY_AND_MEMORY.md).

### Headless (scripts and CI)

`ract -p "prompt"` runs one turn without a terminal. The prompt can also come
on stdin; when both are given, stdin is added to the prompt as labeled context.
stdout carries only the result and progress goes to stderr, so
`ract -p "..." > out.txt` gives a clean file.

A headless run starts in `default` mode, like a session: it would ask
before changing a file, and with no terminal to ask it refuses the change
(exit 3). Pass `--accept-edits` when the run may change files. Answers
need no flag.

```bash
ract -p --accept-edits "fix the failing test"         # the verdict; files may change
ract -p --accept-edits "fix the failing test" --output-format json   # one ract.result/1 object
ract -p "summarize this log" < build.log              # stdin as the prompt's context
ract -p --ask "where is the config loaded?"           # answer only; no plan, no file written
ract -p --accept-edits "fix the failing test" --output-format stream-json   # every event
```

Exit codes: 0 done, 1 the task failed, 2 usage or configuration error, 3
refused, 4 a budget was used up, 5 interrupted, 6 the provider was
unavailable, 143 terminated. The
JSON schema is in `docs/EVENTS_SESSION.md`.

A headless run does not run the repository's own commands (hooks, MCP
servers, test gates) unless the repository is trusted: run `ract trust` as an
earlier step, or pass `--trust-project` for one run. Nothing in the
repository can grant this itself. `--bare` loads none of them even when
trusted. A GitHub Actions step:

```yaml
- name: Ask RACT to fix the failing test
  run: |
    ract -p --accept-edits "fix the failing test" --output-format json > ract-result.json
    jq -e '.outcome == "done"' ract-result.json
```

## CLI Verb Index

Run `ract --help` to see every verb enumerated at the top level; `ract
help <verb>` prints per-verb usage. The list below is generated from
`src/ract/cli_help.py::VERB_DESCRIPTIONS` and cross-checked in CI by
`tests/unit/test_readme_verb_index_matches_parser.py` (v0.5.1 wiring
module_10, Lens A M8 closure).

<!-- BEGIN VERB INDEX (auto-checked; edit VERB_DESCRIPTIONS in src/ract/cli_help.py) -->
- `ract run`: Execute an intent as a planned-and-verified RACT run.
- `ract plan`: Load, save, replay, diff, or analyse a serialized plan.
- `ract session`: List, export, import, backup, or restore saved sessions.
- `ract doctor`: Diagnose RACT installation, config, and workspace state; `--sandbox` says what confines a command here.
- `ract status`: Print a one-line summary of the current workspace state.
- `ract self-audit`: Audit RACT's own code against the audit lens findings.
- `ract audit`: Audit a workspace or run for anti-rot and provenance issues.
- `ract leaderboard`: Print the provider leaderboard by success rate.
- `ract source-digest`: Print the SHA-256 digest of a source file or workspace.
- `ract init`: Initialize a new RACT project from a template.
- `ract docs`: Generate or regenerate documentation for the workspace.
- `ract openapi`: Generate an OpenAPI client or server scaffold.
- `ract provider`: List, add, or configure provider adapters and presets.
- `ract router`: Inspect or reconfigure the provider router policy.
- `ract config`: Inspect or edit ract.yaml keys.
- `ract cost`: Report accumulated provider cost from receipts.
- `ract memory`: Init, apply-narrowings, and inspect memory-discipline indexes.
- `ract retrieval`: Search the retrieval adapter; query the three memory indexes.
- `ract intent`: Operator-signed intent recompile appending a new suite version.
- `ract repl`: Open an interactive session: type intents, use /commands, keep context.
- `ract handshakes`: List, approve, reject, defer, or review pending handshakes.
- `ract operator-queue`: List or drain the operator-approval queue.
- `ract whisper`: Brief the conventions and recent history that bear on a task (writes nothing).
- `ract auction`: List or resolve entries in the dead-code auction.
- `ract fence`: List or resolve Chesterton's fence entries.
- `ract trust`: Trust this repository's own commands and endpoints (hooks, MCP servers, gates), or list and remove trust.
- `ract policy`: The operator key and the signed tier-3 grant: keygen, init --guided, add-rule, sign, status, revoke.
- `ract setup`: Check this machine, choose a local or cloud model, and write a working ract.yaml.
- `ract undo`: Reverse the last RACT turn: restore the files it replaced, remove the files it created.
- `ract redo`: Reverse the last undo.
- `ract skills`: List and inspect builtin and installed skills.
- `ract marketplace`: (alias) Same as skills marketplace; browse skill packages.
- `ract mcp`: Manage and invoke MCP tools registered with RACT.
- `ract refactor`: Run a scoped refactor over a named target.
- `ract rename`: Rename a symbol project-wide through the symbol renamer.
- `ract diff`: Show and apply RACT-authored diffs against the workspace.
- `ract explain`: Explain a plan, step, or artifact with its provenance chain.
- `ract consolidate`: Scan for consolidation candidates and propose merges.
- `ract report`: Render run reports in markdown or HTML.
- `ract trace`: Inspect an events.jsonl trace file, if one exists. No shipped command writes one in this build.
- `ract quality`: Compute the plan quality scorecard.
- `ract load-bearing`: Inspect or manage load-bearing annotations across the workspace.
- `ract novelty`: Report novelty budget usage and scan for overruns.
- `ract coverage`: Report coverage deltas and status.
- `ract mutation`: Run mutation-testing checks over the workspace.
- `ract conformance`: Run the provider conformance suite.
- `ract rot-report`: Print the anti-rot report.
- `ract rot`: Detect and quarantine rot in the workspace.
- `ract merge-gate`: Evaluate the mutation-testing merge gate.
- `ract provenance`: Verify Rootknot signatures for artifacts and workspaces.
- `ract verify`: Check a commit range and/or a run: every changed line attributed to a signed step, each Rootknot verified, the trace chain when the run has one.
- `ract receipt`: List, show, or verify receipts.
- `ract receipt-export`: Print the signed receipts in a directory as JSON.
- `ract manifest`: Repro-manifest alias + ledger verify/inspect/show/proof.
- `ract repro-manifest`: Produce a reproducibility manifest for a run.
- `ract policy-gate`: Evaluate a run against the configured policy.
- `ract run-fingerprint`: Print or diff a run's fingerprint.
- `ract ai-sbom`: Emit an AI Software Bill of Materials.
- `ract release`: List, create, or update GitHub releases.
- `ract calibrate`: Run provider calibration (experimental).
- `ract infer`: Run a single inference call (experimental).
<!-- END VERB INDEX -->

New to tier 3: [docs/TIER3.md](docs/TIER3.md).

### Core sub-verbs (quickstart pointers)

The auto-generated index above lists every top-level verb. These are the
sub-verbs first-run users reach for most often; each is asserted by
`tests/test_readme_cli_index.py` + `tests/test_readme_version.py` so
first-run docs stay honest:

- `ract run`: start a run from an intent
- `ract doctor`: one-shot workspace health check
- `ract config validate`: check `ract.yaml` before running
- `ract provider health`: verify every provider adapter can reach its backend
- `ract session list`: enumerate persisted session directories
- `ract plan diff`: compare two serialized plans
- `ract fence inspect --file <path>`: inspect Chesterton's-fence entries in a file

Anti-lazy gates (G1-G8) are pre-commit helpers rather than top-level CLI verbs.
A run records its audit trail in the egress ledger in the user state
directory, in the signed Rootknot sidecars beside the files it wrote and the
`.ract/rootknots.db` index, and, when a caller asks for it, in the session
events from `--output-format stream-json`. A normal run writes no report
files; the gate report shapes the README listed here in earlier drafts
(`mutation_kill.json`, `patch_diff.json`, `coverage_delta.json` and friends)
exist as library functions the test suite exercises.

## What makes RACT different

- **Provenance-anchored artifacts**: every file the loop writes carries a signed `Rootknot` binding it to its plan step, assumption, generator, and parent artifacts; a run that could not sign its files says so in the turn summary. See [`docs/PROVENANCE.md`](docs/PROVENANCE.md).
- **Assumption-driven programming**: assumptions live in a registry with a four-state lifecycle (`proposed`, `active`, `discharged`, `violated`); violations propagate through the dependency graph.
- **Milestone-halting recursion**: the loop halts on completion, regression, provenance violation, assumption cascade, budget exhaustion, handshake block, or provider fault, each with a distinct termination cause. On a refactoring task this spends measurably fewer tokens than a naive fixed-iteration loop, see [`evals/benchmarks/refactor-token-usage/report.md`](evals/benchmarks/refactor-token-usage/report.md).
- **Operator Handshake**: high-risk actions queue for async review instead of blocking the loop.

## Architecture

Core modules live in `src/ract/core/`: `rootknot.py` (signed provenance), `assumption.py` (`Assumed[T]` registry), `plan.py` (schema + validator), `loop.py` (T1–T7 recursion). See `docs/ARCHITECTURE.md` for the system diagram, boundary contracts, and failure modes; `docs/ADRs/` for decision records.

## Evals & Benchmark

Three reproducible tasks under `evals/tasks/` (reports in `evals/runs/`). See [`evals/README.md`](evals/README.md) for the eval-tree tour. `evals/benchmarks/refactor-token-usage/` compares the milestone-driven loop against a naive baseline on tokens-to-pass; reproduce with `python evals/benchmarks/refactor-token-usage/report.py`.

## Verify

```bash
ract doctor                              # workspace health + dependencies
ract provenance verify <file>             # check a file's Rootknot (RK-1 + RK-2 + RK-3 + AL-1)
ract conformance run --provider fake     # run the per-provider conformance corpus
ract trace replay <run_id>               # replays a saved event log; no shipped command writes one in this build
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

PolyForm Noncommercial License 1.0.0, free for personal use, research, education, and noncommercial organizations; commercial use requires an agreement. See [`COMMERCIAL.md`](COMMERCIAL.md) and [`AUTHOR.md`](AUTHOR.md).

## Known limitations

- Windows file-watcher tests can be flaky under heavy I/O.
- MCP tools run serially within a plan step.
- Benchmark numbers are machine-specific; re-run on your hardware.

---

License: PolyForm Noncommercial 1.0.0. Measurements: take them as one data point from one machine on one day, and re-run on yours.

---

**Author:** Dr. Lucas Root, Ph.D., [info@lucasroot.com](mailto:info@lucasroot.com)

<!-- RACT 0.5.1 -->
