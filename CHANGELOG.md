:warning: This file is project documentation, not part of the source code.

# Changelog

All notable changes to RACT will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.2] - 2026-07-16

### Fixed
- Anti-rot detectors now catch copy-and-rename clones. `duplication_guard`, `consolidate`, and `compression_novelty_detector` all compare AST-normalized structure, so renaming identifiers no longer defeats the duplication gate.
- `duplication_guard` no longer short-circuits on symbol name equality; cross-module renamed duplicates now surface.
- `ract marketplace` dispatches as a top-level verb without argparse rejecting `list`.
- Scrubbed a Windows-specific path from `scripts/run_mutation_tests_wsl.sh`; ROADMAP clarifies mutation testing is local/WSL-only, not a CI gate.
- `src/rootact/__init__.py` version aligned with `pyproject.toml`.

### Added
- `rootact.github_release` client and `ract release list` / `ract release create` commands (reads `github.owner`/`github.repo` from `rootact.yaml` and `GITHUB_TOKEN` from the environment).
- `rootact.ast_normalizer` — canonical identifier renaming, docstring/annotation stripping, and Jaccard similarity over normalized tokens.
- Natural-Language Mutation Merge Gates (`ract mutation merge-gate`) — engine, tests, and CLI verb for gating merges with structured risk review.
- Operator Handshake queue (`rootact.handshake`) — raise, list, answer, and attestation flow for high-risk actions.
- Signed run receipts (`rootact.receipt`) — HMAC sign/verify/save/load with round-trip tests.
- Receipt export (`rootact.receipt_export`) — anonymized export over signed receipts directory.
- Rot report duplicate scan (`rootact.rot_report`) — `find_duplicate_blocks` via structural similarity + tests.
- Configurable CI Policy Gate (`rootact.policy_gate`) — `evaluate_policy` and `policy-gate` CLI verb.
- Run Fingerprint + AI-SBOM (`rootact.run_fingerprint`, `rootact.ai_sbom`) — artifact provenance manifest builder.
- Retrieval adapter enhancements — `KeywordRetrievalAdapter.index()` / `keyword_search()` inverted-index API, `WebSearchAdapter` response normalization, and expanded tests.
- Capability registry circular-import fix and provider-router health tests.
- Anti-rot regression suite covering verbatim and renamed clones across all three detectors.

## [0.1.1] - 2026-07-09

### Fixed
- Symbol graph import resolution now correctly resolves `src/<pkg>` layouts; dead-code auction no longer flags live modules as dead.
- Novelty detector now uses AST-normalized similarity and nearest-neighbor scoring; verbatim duplicates are blocked before write.
- `ract fence` relative-path crash fixed.
- `ract marketplace` dispatch fixed.
- `ract refactor` Windows path-separator bug fixed.

### Added
- `ract consolidate` — scans for near-duplicate modules and proposes safe merges.
- `ract audit` meta-command with deep self-audit mode.
- Per-file mutation-test floors and coverage-delta gate (`rootact coverage delta`).
- MCP adapter with SSE transport.
- Skill marketplace install path.
- Session config persistence and `rootact report --last` fallback.
- Public leaderboard design doc (`docs/PUBLIC_LEADERBOARD.md`).
- Hugging Face Space static landing page (`hf-space/`).
- Demo asciicast (`assets/demo.cast`).
- CLI smoke tests for core verbs and CI self-audit job.

### Changed
- README now includes status badges and a "Why RACT" comparison table.
- Documentation expanded: `AUDIT.md`, `PROVIDER_SETUP.md`, `HARNESS.md`, `SKILL_AUTHORING.md`, `SEPARATION.md`, `PHILOSOPHY.md`.

## [0.1.0] - 2026-07-08

### Added
- Initial public release of RACT (Root Agentic Coding Tool).
- Model-agnostic provider layer with presets for local, OpenAI, Anthropic, Z.ai, Moonshot, and OpenRouter.
- Root-Knot-anchored self-recursing build loop with Progress Oracle milestone tracking.
- `Rooted[T]` assumption-driven result type.
- Operator Handshake registry for high-risk actions.
- Anti-rot verifier arsenal:
  - `rootact novelty scan` — compression-based novelty detection.
  - `rootact whisper` — Legacy Whisperer pre-planning dialect brief.
  - `rootact auction list` — Dead Code Auction candidate scanner.
  - `rootact fence inspect` — Chesterton's Fence legacy-code reason subagent.
- Built-in skill library with 7 signed templates.
- MCP adapter, DiffApplier, and retrieval adapter (keyword + web search).
- Run reports with JSON export.
- Multi-file symbol rename (`rootact refactor`).
- OpenAPI client/server generation.
- Project health diagnostics (`rootact doctor`).
- Branded terminal UI with colorized input/output and rich tables.
- Documentation: README, QUICKSTART, TUTORIAL, ARCHITECTURE, PHILOSOPHY, PROVIDER_SETUP, SKILL_AUTHORING, AUDIT, SEPARATION.

### License
- Released under the PolyForm Noncommercial License 1.0.0.

---

*Dr. Lucas Root, Ph.D.*

<!-- RACT 0.1.1 - Trust and tooling -->
