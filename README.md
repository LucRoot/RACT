# RACT (Root Agentic Coding Tool)

<p align="center">
  <img src="https://raw.githubusercontent.com/LucRoot/RACT/main/assets/DrLucasRoot-Logo.png" alt="Dr. Lucas Root logo" width="180">
</p>

**Model-agnostic, local-first agentic coding with signed receipts and an anti-rot verifier arsenal.**

![RootAct CI](https://github.com/LucRoot/RACT/actions/workflows/ci.yml/badge.svg)
![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/LucRoot/RACT/main/docs/coverage-badge.json)
![Lint](https://img.shields.io/badge/lint-ruff-261230)
![Types](https://img.shields.io/badge/types-mypy-blue)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![Mutation](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/LucRoot/RACT/main/docs/mutation-badge.json)

A 2024 analysis of **623 million commits** by GitClear and GitKraken found that AI-assisted code is already rotting codebases: more copy/paste, less refactoring, and a measurable decline in code movement. RACT is the first agentic coding tool built to measure and defend against the four rot vectors that research identified — duplication, drift, dead code, and undocumented load-bearing logic.

RACT keeps the human in the loop while a small management LM routes work to the right provider. Every plan and every result is `Rooted[T]` — it carries the assumption, confidence, and provenance that justify it. Every generated file carries the **Root Knot** (`_ROOT_KNOT = object()`), so unsigned drift breaks the loop instead of compounding.

## Quickstart

```bash
ract run        # start a Rooted agent loop on your intent
ract doctor     # verify project config and provider health
ract fence      # inspect why legacy code exists before changing it
```

## CLI Verb Index

| Command | What it does |
|---|---|
| `ract run <intent>` | Start a Rooted agent loop on your intent. |
| `ract doctor [--json]` | Verify project config and provider health. |
| `ract config validate` | Validate `rootact.yaml` structure. |
| `ract config diff --before <path> --after <path> [--json]` | Compare two rootact.yaml files. |
| `ract provider health [--json|--markdown]` | Check reachability of configured providers. |
| `ract provider scorecard --receipts-dir <dir> [--json|--csv]` | Aggregate provider statistics from receipts. |
| `ract quality scorecard [--json]` | Score a sample anti-rot verdict. |
| `ract self-audit [--json|--html]` | Audit project for Root Knot markers. |
| `ract status [--json|--markdown]` | Print project status dashboard. |
| `ract session list` | List saved session IDs. |
| `ract session export --session <id> --output <path>` | Export a session to JSON. |
| `ract session import --input <path>` | Import a session from JSON. |
| `ract plan diff <a> <b>` | Diff two saved plans. |
| `ract init --list-templates` | List available project templates. |
| `ract auction list|html-report` | Find dead code or export an HTML report. |
| `ract leaderboard --receipts-dir <dir> [--json]` | Render receipt leaderboards. |
| `ract coverage delta|baseline|status|badge` | Earned-coverage gates. |
| `ract novelty scan [--fast] [--json|--html] [--timeout <sec>]` | Measure code novelty vs. the codebase. |
| `ract receipt show|verify|chain-export [--json]` | Inspect signed receipts and chains. |
| `ract receipt export --directory <dir> [--markdown]` | Export anonymized receipts as Markdown table. |
| `ract fence inspect --file <path> [--json|--csv]` | Ask why legacy code exists. |
| `ract merge-gate --policy <json>` | Evaluate merge policies. |
| `ract policy-gate --policy <json> --evidence <json> [--json|--markdown|--csv]` | CI policy evaluation. |
| `ract router select --intent <hint> [--markdown]` | Select provider for a capability hint. |
| `ract router health [--json|--markdown]` | Check configured provider health. |
| `ract infer <task> [--config rootact.yaml] [--json|--markdown]` | Score and route a task through the 3-tier inference router. |
| `ract calibrate --receipts-dir <dir> [--json] [--output <path>]` | Calibrate complexity-router tier thresholds from receipts. |
| `ract run-fingerprint <receipt.json> [--json]` | Fingerprint a run for reproducibility. |
| `ract ai-sbom <receipts.json>` | Build an AI provenance manifest. |
| `ract manifest --receipts-dir <dir>` | Export AI provenance manifest from a directory. |
| `ract repro-manifest --intent <text> --plan <file> --config <file> [--fingerprint <str>] [--output <path>]` | Build a canonical reproducibility manifest. |
| `ract grove-forge eval --results-dir <dir> [--learning-feed]` | Summarize Grove Forge benchmark results and feed learnings. |
| `ract grove-forge guardian --reports-dir <dir> [--learning-feed]` | Scan Grove Forge artifacts for Root Knot markers. |
| `ract report --last --format markdown|html|json --output <path>` | Export the last run report in the chosen format. |
| `ract cost summary --receipts <path> [--json|--csv]` | Summarize run receipt costs. |
| `ract consolidate --dry-run` | Preview near-duplicate module merges. |
| `ract release list|create` | List or create GitHub releases. |
| `ract rot baseline --history <path> [--json]` | Record a rot-trend baseline snapshot. |
| `ract fence inspect --file <path>` | Ask why legacy code exists. |
| `ract retrieval search <query> --json` | Search retrieval context as JSON. |
| `ract diff apply --patch <path> --json` | Apply a patch and report results as JSON. |
| `ract skills list [--json]` | List built-in RACT skills. |
| `ract skills marketplace list [--json]` | List skills from a marketplace catalog. |
| `ract mcp list [--json]` | List tools exposed by configured MCP servers. |
| `ract mutation run [--json]` | Run mutation tests and report as JSON. |
| `ract refactor --old <n> --new <n> --dry-run --json` | Preview symbol renames as JSON. |
| `ract whisper --intent <text> [--json]` | Generate a codebase brief as JSON. |

## Demo

```bash
$ rootact --welcome
        ╭──────────────────────────────────╮
        │  Root Knot  · Agentic Coding Tool      │
        ╰──────────────────┬───────────────╯
                           │
        ╭──────────────────┴───────────────╮
        │         ✦  The Root Knot  ✦          │
        ╰──────────────────────────────────╯
        Every plan Rooted. Every file carries the Knot.

╭─ Welcome to RACT ────────────────────────────────────────────────────────────╮
│ Version: 0.1.2                                                               │
│ Author: Dr. Lucas Root, Ph.D.                                                │
│ License: PolyForm Noncommercial License 1.0.0                                │
│                                                                              │
│ RACT keeps the human in the loop while a small management LM routes work to  │
│ the right provider.                                                          │
│                                                                              │
│ Quick commands:                                                              │
│   rootact --init-provider local     · scaffold a project for a local model   │
│   rootact 'your intent' --loop       · run a Root-Knot-anchored build loop   │
│   rootact report --last              · see what changed and why              │
│   rootact whisper --intent '...'     · get a codebase dialect brief          │
│   rootact auction list               · review dead-code candidates           │
│   rootact fence inspect --file f.py  · ask why legacy code exists            │
│   rootact consolidate --dry-run      · preview near-duplicate module merges   │
╰──────────────────────────────────────────────────────────────────────────────╯
```

A recorded session is available: [`assets/demo.cast`](assets/demo.cast). Play it locally with:

```bash
asciinema play https://raw.githubusercontent.com/LucRoot/RACT/main/assets/demo.cast
```

[![asciicast](https://asciinema.org/a/demo.svg)](https://asciinema.org/a/demo)

## Why RACT instead of Cursor, Claude Code, or Lovable?

| Dimension | RACT | Cursor | Claude Code | Lovable |
|---|---|---|---|---|
| **Pricing model** | Free to run locally; pay only for tokens you route | $20/mo subscription + token costs | $20/mo subscription + token costs | Subscription tiers + token costs |
| **Provider lock-in** | Model-agnostic: local, OpenAI, Anthropic, Z.ai, Moonshot, OpenRouter | Mostly Anthropic / OpenAI | Anthropic only | Closed, hosted stack |
| **Loop logic** | **Progress Oracle**: milestone-driven recursion | Time-based or user-prompted | User-prompted turns | Single-shot or chat turns |
| **Continuity guard** | **Root Knot**: every file carries an identity sentinel; unsigned drift breaks the loop | None built-in | None built-in | None built-in |
| **Anti-rot tooling** | `consolidate`, `novelty scan`, `whisper`, `auction`, `fence` as first-class CLI verbs | Not a core feature | Not a core feature | Not a core feature |
| **Earned quality gates** | `coverage delta`, `mutation run`, and lint/format repair as CLI verbs | Editor lint only | Editor lint only | Editor lint only |
| **Human oversight** | **Operator Handshake**: high-risk items queue for async review | Inline approval dialogs | Inline approval dialogs | Inline approval dialogs |
| **Auditability** | Signed receipts for every run; quality comparable across models | Session history | Session history | Limited |
| **Execution model** | CLI-first, own your pipeline | IDE-integrated | Terminal inside IDE | Web-hosted |
| **Diff strategy** | Surgical unified-diff application | Inline diff widget | Inline diff widget | Full-file rewrites |
| **Local data** | Runs entirely locally if you choose | Cloud providers required | Cloud providers required | Cloud-hosted |

RACT is for developers who already live in the terminal, want to mix cheap local and frontier models, and need reproducible, auditable agent runs. Cursor and Claude Code are smoother if you want an IDE-integrated experience; Lovable is faster if you want to generate a SaaS UI in one sentence. RACT wins on sovereignty and model economics.

### Anti-rot workflow

RACT exposes the rot-fighting loop as first-class CLI verbs:

- `rootact consolidate --dry-run` — find near-duplicate modules and preview merges before enqueuing them for operator approval.
- `rootact novelty scan` — measure how much a new artifact resembles existing code; blocks near-duplicates before they are written.
- `rootact auction list` — identify dead code by reachability and queue it for removal.
- `rootact fence inspect --file <path>` — ask why legacy code exists before changing it.

See `docs/ARCHITECTURE.md` and `docs/PHILOSOPHY.md` for the design rationale.

## Install

RACT ships as a pure-Python wheel for Windows, macOS, and Linux.

```bash
pip install rootact
```

`ract` is also provided as a shorter alias for `rootact`.

Or use the one-line installer:

```bash
# macOS / Linux
curl -sSL https://raw.githubusercontent.com/LucRoot/RACT/main/scripts/install.sh | bash

# Windows (PowerShell)
pip install rootact
```

## Quick start

Scaffold a complete project in one command:

```bash
rootact init --template python-package --provider local
```

Create a provider preset:

```bash
rootact --init-provider local
```

Plan without executing:

```bash
rootact "refactor this function to use async" --dry-run
```

Execute a single intent:

```bash
rootact "add input validation to the login endpoint" --yolo
```

Run the Root-Knot-anchored self-recursing build loop:

```bash
rootact "implement a file watcher that rebuilds on change" --loop --max-iterations 10
```

The loop stops when the work is done, a regression is detected (tests fail, quality drops, or the Root Knot sentinel is missing), or the maximum number of iterations is reached. Each iteration is bounded by a configurable timeout so a hung provider cannot stall the loop.

## Terminal experience

RACT is terminal-first. Run `rootact --welcome` to see the Root-Knot logo and a quick-command panel. User input is highlighted in cyan, direct system-to-user messages in orchid, and listing commands render as rich tables. Set `NO_COLOR=1` to disable styling.

## CLI highlights

- `rootact --dry-run` — Plan only; see the proposed steps and quality score.
- `rootact --yolo` / `rootact --auto` — Execute without prompts or require approval per step.
- `rootact --reload` — Re-run the intent once after a successful execution.
- `rootact --loop` — Run in the Root-Knot-anchored recursion loop with milestone tracking.
- `rootact --max-iterations N` — Cap the recursion loop.
- `rootact --mode {default,documentation,git}` — Switch between normal coding, documentation generation, and git-assist modes.
- `rootact --session SESSION_ID` — Save and resume long-running sessions with rollback support.
- `rootact --project-doc PATH` — Load a project document that prepends goal and constraints to every intent.
- `rootact --self-test` — Run RACT's internal test suite.
- `rootact --review-diff PATH` — Review a unified diff.
- `rootact --stream` — Stream provider responses to stdout.
- `rootact --init-provider {local,openai,anthropic,zai,moonshot,openrouter}` — Write a starter `rootact.yaml`.
- `rootact skills list/install/install-all` — Manage built-in skill templates.
- `rootact skills marketplace list` — Browse the public skill marketplace.
- `rootact skills marketplace install --name <skill>` — Install a marketplace skill into the project.
- `rootact consolidate --dry-run` — Preview near-duplicate module merges.
- `rootact consolidate scan|apply|rollback` — Find, apply, and rollback module consolidations.
- `rootact report --last` / `--session ID` — View a structured summary of the last run or session.
- `rootact report --last --format json --output report.json` — Export a structured run report for scripts or CI.
- `rootact report --last --format markdown --output report.md` — Export a human-readable Markdown run report.
- `rootact report --last --format html --output report.html` — Export a self-contained HTML run report.
- `rootact handshakes list/approve/reject/defer` — Review high-risk milestones that the loop deferred.
- `rootact mcp list` — Inspect tools exposed by configured MCP servers.
- `rootact retrieval search <query>` — Preview what context RACT retrieves for a query.
- `rootact diff apply --patch <path> [--dry-run]` — Apply a unified-diff patch file surgically.
- `rootact explain --intent <text>` / `--plan <path>` — Preview a dry-run plan in plain language.
- `rootact novelty scan [--json]` — Preview compression-based novelty scores for project files (local, no model call).
- `rootact whisper --intent "..."` — Ask the Legacy Whisperer for a pre-planning dialect/history brief.
- `rootact auction list [--min-age-days N] [--json]` — Review old, unreferenced modules proposed for deletion.
- `rootact fence inspect --file <path> [--lines N-M]` — Ask Chesterton's Fence for a plausible reason legacy code exists before changing it.
- `rootact coverage delta --run --min-percent 90.0` — Run tests and fail if coverage regresses or drops below a floor.
- `rootact mutation run [--wsl-distro <name>]` — Run mutation tests against the four core engine files locally (WSL2 on Windows; native bash elsewhere). Mutation testing is a heavyweight local diagnostic, not a CI gate.
- `rootact --about` — Show authorship, license, and Root Knot statement.
- `rootact --welcome` — Print the branded Root-Knot welcome letter.
- `rootact init --template <name> --provider <name>` — Scaffold a new project from a template.
- `rootact docs generate` — Generate Markdown API docs from source docstrings.
- `rootact refactor --old <name> --new <name>` — Safely rename a module-level symbol across files.
- `rootact openapi generate-client --spec <path> --output <path>` — Generate an `httpx`-based Python client from an OpenAPI 3 spec.
- `rootact openapi generate-server --spec <path> --output <path>` — Generate a FastAPI server module from an OpenAPI 3 spec.
- `rootact plan export --session <id> --output <path>` — Save a session plan to JSON for reproducibility.
- `rootact plan replay --plan <path> --dry-run` — Replay a saved plan and report per-step success.
- `rootact doctor [--check-providers]` — Run config diagnostics and optionally ping each provider endpoint.

## Built-in skills

RACT ships with signed skill templates for common tasks:

- `python-package` — Scaffold a clean Python package with pyproject.toml, src layout, tests, and RACT identity markers.
- `fastapi-app` — Build a small FastAPI application with routes, models, and tests.
- `react-component` — Generate a React component with props, tests, and a story file.
- `test-generation` — Generate comprehensive tests for existing code, including edge cases and Root Knot verification.
- `documentation-update` — Update README, ARCHITECTURE, and inline docs before touching implementation.
- `cli-tool` — Scaffold a Python CLI tool with argparse, tests, and a signed entry point.
- `library-refactor` — Refactor existing code while preserving behavior and Root Knot signatures.

Install one:

```bash
rootact skills install python-package
```

Install all:

```bash
rootact skills install-all
```

## Skill marketplace

Beyond the built-ins, RACT can install skills from a marketplace catalog. The default catalog is hosted in this repository:

```bash
rootact skills marketplace list
rootact skills marketplace install --name hello-world
```

A marketplace skill is a JSON file containing a string template and optional tool references. You can publish your own catalog by passing `--catalog <url-or-path>`.

## MCP tools

RACT can invoke tools exposed by MCP servers. Add an `mcp_servers:` section to `rootact.yaml`, then inspect what is available:

```bash
rootact mcp list
```

Each listed tool can be called from plan steps, letting RACT use filesystem, browser, database, or documentation servers that you already run locally.

## The Root Knot

Every non-init Python file carries three identity markers:

```python
__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
```

The `_ROOT_KNOT` sentinel is not just a signature — it is a loop invariant. If the recursion loop ever produces an artifact without the knot, the loop stops immediately rather than compounding unsigned work. This is how RACT turns authorship into a safety property.

## Signed receipts

Every RACT run produces a structured receipt. Export one:

```bash
rootact report --last --format json --output report.json
```

Receipts capture intent, model, steps, test results, quality score, cost, latency, and the final decision. Over time they become a dataset for comparing providers, debugging regressions, and running a public quality leaderboard — a surface no incumbent can copy because it depends on verifiable, signed completion records rather than marketing claims.

## Architecture

RACT is intentionally model-agnostic. The harness wires together:

- `Manager` — turns an intent into a JSON plan.
- `Planner` / `PlanValidator` — validates plan shape and detects cyclic dependencies.
- `Executor` — dispatches each step to the provider selected by the capability-based router, writes artifacts to disk, and applies safety guardrails.
- `Rooted[T]` — every plan and result carries the assumption that justifies it.
- `LoopController` / `ProgressOracle` / `MilestoneOracle` — the recursion engine that plans milestones, verifies them, and decides when the work is truly done.
- `HandshakeRegistry` — high-risk actions never pause the loop; they accumulate for operator review.
- `RunReporter` — structured summaries of every loop/session.
- `SignatureGuardian` — verifies that signature markers remain intact across the codebase.

See `docs/ARCHITECTURE.md` and `docs/PHILOSOPHY.md` for the design rationale.  
Try the live demo landing page on [Hugging Face](https://huggingface.co/spaces/LucRoot/RACT).

## Independence

RACT is built from scratch against a public research specification for agentic coding tools. It is intentionally independent of the author's proprietary internal tooling: no proprietary code, design, or internal ideas are included. See `docs/SEPARATION.md`.

## About the author

See [`AUTHOR.md`](AUTHOR.md).

## Contributing

We welcome contributions. Please see [`CONTRIBUTING.md`](CONTRIBUTING.md) for guidelines, including the Contributor License Agreement requirement.

## Security

If you discover a security vulnerability in RACT, please email **info@lucasroot.com** rather than opening a public issue. See [`SECURITY.md`](SECURITY.md) for the full policy.

## License

RACT is licensed under the **PolyForm Noncommercial License 1.0.0** — free for personal use, research, education, and noncommercial organizations.

Commercial use requires a separate license agreement. See [`COMMERCIAL.md`](COMMERCIAL.md) for details, or email info@lucasroot.com.

Copyright 2026 Dr. Lucas Root, Ph.D.

<!-- RACT 0.1.2 - Trust and tooling -->
