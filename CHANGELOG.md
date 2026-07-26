:warning: This file is project documentation, not part of the source code.

# Changelog

All notable changes to RACT (Root Agentic Coding Tool) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] - 2026-07-25 — Auditability and Depth

### Added

- **Public provenance statement** — `docs/PROVENANCE.md` is the single public document describing what a Rootknot attests, how RACT stays independent of private systems, how to verify a Rootknot, and what happens on violation (T3 `PROVENANCE_FAILURE`).
- **Independence lint** — `tests/test_public_provenance.py` AST-scans `src/ract/` and fails the build if any module imports from a root not in the curated allowlist. Adding a third-party dependency is now a conscious, reviewed act.
- **Failure-mode architecture** — `docs/ARCHITECTURE.md` gained a "Failure modes and concurrency" section; every named failure maps to a real `TerminationCause` or the `authorize_action` gate.
- **Two new ADRs** — [ADR-0008](docs/ADRs/ADR-0008-ract-yaml-versioning.md) (`ract.yaml` schema versioning) and [ADR-0009](docs/ADRs/ADR-0009-mcp-tool-execution-boundaries.md) (MCP/tool-execution boundaries), each with rejected alternatives. The repo now carries 9 ADRs.
- **Benchmark harness** — `evals/benchmarks/refactor-token-usage/` compares the milestone-driven loop against a naive fixed-iteration baseline on tokens-to-pass, with a committed `report.md` and a CI `benchmark` job. The contender is strictly better (80% fewer tokens on the refactor task).
- **Rootknot ergonomics** — `SessionKey.rotate()` archives the old key (pre-rotation rootknots still verify); `ract provenance verify <path>` CLI verb prints `valid`/`invalid`; the executor optionally signs and indexes every artifact write (SQLite + sidecar) when configured.
- **Repo hygiene** — `tests/fixtures/` convention with a hygiene lint test (no tracked root JSON, runtime dirs gitignored); CONTRIBUTING documents branch-protection requirements and repository conventions.

### Changed

- README trimmed to under 500 words; every public claim now references a command or a committed report. Added a "Verify" section.
- CI runs `ruff` over `evals/` and adds the `benchmark` job with report artifact upload.

### Removed

- The `_ROOT_KNOT = object()` sentinel deprecation note is retired — the sentinel is fully gone from `src/` and `tests/` (verified by grep).

### Known limitations (carried to the hardening backlog)

- `ract.yaml` schema-version enforcement (ADR-0008) is documented but not yet implemented in `config.py`.
- The benchmark proves the termination mechanism on one deterministic task; a multi-task sweep with varied pass-iteration profiles is queued.
- `ract provenance verify` resolves the generator public key from the local key store (the sidecar stores the key *id*, not the raw pubkey); embedding the raw pubkey in the sidecar is queued.
- Branch protection is documented; applying the GitHub settings is an operator action.

## [0.2.0] - 2026-07-23 — Provenance and Invariants

### Added

- **Signed Rootknot provenance** — every artifact carries an ed25519-signed `Rootknot` binding it to its plan step, assumption, generator, and parent artifacts. See [ADR-0001](docs/ADRs/ADR-0001-provenance-anchored-artifacts.md).
- **Provenance workspace verifier** — `verify_workspace` checks invariants RK-1 and RK-2 before every recursion step. See `src/ract/core/provenance.py`.
- **Assumption registry** — four-state lifecycle (`proposed`, `active`, `discharged`, `violated`) with transitive violation propagation. See [ADR-0002](docs/ADRs/ADR-0002-assumption-registry.md).
- **Formal loop termination** — recursion halts on T1–T7 with a distinct `TerminationCause`. See [ADR-0003](docs/ADRs/ADR-0003-milestone-driven-recursion.md).
- **Threat model** — capability tiers T0–T3, sandbox gating, and a published refuse-list. See [ADR-0004](docs/ADRs/ADR-0004-tool-execution-threat-model.md) and [ADR-0007](docs/ADRs/ADR-0007-what-ract-refuses.md).
- **Capability-based provider routing** — router selects providers by capability hint and health. See [ADR-0005](docs/ADRs/ADR-0005-provider-capability-routing.md).
- **Deferred-approval handshakes** — high-risk actions queue for async operator review. See [ADR-0006](docs/ADRs/ADR-0006-deferred-approval-handshakes.md).
- **Versioned plan schema** — `src/ract/core/schemas/plan-v1.json` with migration support.
- **Eval harness** — three reproducible tasks under `evals/tasks/` with committed run reports in `evals/runs/`.

### Changed

- README rewritten to a concise, technical pitch; author content moved to `AUTHOR.md`.
- CI badge and coverage badge added to README.

### Deprecated

- The `_ROOT_KNOT = object()` sentinel is retained as a legacy fallback through v0.2.0 and will be removed in v0.3.0.

## 0.1.2

### Added

- **Signed receipts and receipt chain**: every run produces a signed receipt; receipts can be chained tamper-evidently and exported.
- **Handshake queue**: operator handshakes queue high-risk items for async review.
- **Dead-code auction**: `ract auction list` identifies unreachable modules; `ract auction html-report` exports HTML reports.
- **AI provenance manifest / SBOM**: `ract ai-sbom` and `ract manifest` build and export AI provenance manifests.
- **Configurable CI policy gate**: `ract policy-gate` evaluates JSON policies against run evidence.
- **Coverage delta**: `ract coverage delta|baseline|status|badge` implements earned-coverage gates.
- **Mutation merge gate**: `ract merge-gate` evaluates natural-language merge policies against mutation metrics.
- **Native internal provider**: route prompts to local scripts via `adapter: internal`.
- **MCP adapter health probe**: verify MCP tool wiring before running loops.
- **Receipt leaderboard**: `ract leaderboard` renders model/plan ranking tables from receipts.
- **Deterministic run fingerprints**: `ract run-fingerprint` fingerprints runs for reproducibility studies.
- **Run report exports**: Markdown, HTML, and JSON run reports for CI artifacts.
- **Quality scorecard JSON export**: archive and compare quality scorecards across runs.
- **Novelty scan fast mode**: `ract novelty scan --fast` finishes in seconds for CI.
- **New CLI verbs**:
  - `ract --version`
  - `ract config validate`
  - `ract provider health`
  - `ract session list`
  - `ract plan diff`
  - `ract init --list-templates`
  - `ract doctor --json`
- **JSON output flags** across the CLI surface:
  - `ract retrieval search --json`
  - `ract diff apply --json`
  - `ract skills list --json` and `ract skills marketplace list --json`
  - `ract mcp list --json`
  - `ract run-fingerprint --json`
  - `ract leaderboard --json`
  - `ract mutation run --json`
  - `ract refactor --dry-run --json`
  - `ract whisper --json`
- **Diff applier context verification**: `ract diff apply` now validates hunk context before writing and parses both git-style and plain unified-diff headers.

### Changed

- Thermal governance in the build loop now uses a hard ceiling and a separate concurrency-fallback threshold.
- Provider router now registers the `internal` adapter by default.

## 0.1.1

- Trust and tooling release: dead-code auction, Chesterton's Fence, consolidation, rot report, and provider routing.

## 0.1.0

- Initial public release of RACT.
