# RACT (Root Agentic Coding Tool)

<p align="center">
  <img src="https://raw.githubusercontent.com/LucRoot/RACT/main/assets/DrLucasRoot-Logo.png" alt="Dr. Lucas Root logo" width="180">
</p>

**Model-agnostic, local-first agentic coding with signed receipts and an anti-rot verifier arsenal.**

A 2024 analysis of **623 million commits** by GitClear and GitKraken found that AI-assisted code is already rotting codebases: more copy/paste, less refactoring, and a measurable decline in code movement. RACT is the first agentic coding tool built to measure and defend against the four rot vectors that research identified — duplication, drift, dead code, and undocumented load-bearing logic.

RACT keeps the human in the loop while a small management LM routes work to the right provider. Every plan and every result is `Rooted[T]` — it carries the assumption, confidence, and provenance that justify it. Every generated file carries the **Root Knot** (`_ROOT_KNOT = object()`), so unsigned drift breaks the loop instead of compounding.

[![RACT session](https://asciinema.org/a/placeholder.svg)](https://asciinema.org/a/placeholder)

## Why RACT instead of Cursor, Claude Code, or Lovable?

1. **Progress Oracle** — milestone-driven recursion instead of time-based looping.
2. **Root Knot invariant** — the author's identity marker doubles as a loop safety check. Unsigned work cannot compound.
3. **Provider presets** — one-command setup for local, OpenAI, Anthropic, Z.ai, Moonshot, and OpenRouter. Own your pipeline, own your model economics.
4. **Anti-rot verifier arsenal** — `rootact novelty scan`, `rootact whisper`, `rootact auction list`, and `rootact fence inspect` are first-class CLI verbs, not afterthoughts.
5. **Built-in skill library** — 7 signed templates installable from the CLI.
6. **Operator Handshake** — high-risk milestones queue for review instead of blocking the loop.
7. **Signed receipts** — every completed run produces a structured report. Quality becomes measurable and comparable across models. A public leaderboard is coming.
8. **MCP Integration** — call external tools (filesystem, database, browser, docs) from plan steps.
9. **Surgical diffs** — apply unified diffs to existing files instead of rewriting them whole.
10. **Retrieval** — keyword and web-search adapters surface relevant context before planning.

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
- `rootact report --last` / `--session ID` — View a structured summary of the last run or session.
- `rootact report --last --format json --output report.json` — Export a structured run report for scripts or CI.
- `rootact handshakes list/approve/reject/defer` — Review high-risk milestones that the loop deferred.
- `rootact mcp list` — Inspect tools exposed by configured MCP servers.
- `rootact retrieval search <query>` — Preview what context RACT retrieves for a query.
- `rootact diff apply --patch <path> [--dry-run]` — Apply a unified-diff patch file surgically.
- `rootact explain --intent <text>` / `--plan <path>` — Preview a dry-run plan in plain language.
- `rootact novelty scan [--json]` — Preview compression-based novelty scores for project files (local, no model call).
- `rootact whisper --intent "..."` — Ask the Legacy Whisperer for a pre-planning dialect/history brief.
- `rootact auction list [--min-age-days N] [--json]` — Review old, unreferenced modules proposed for deletion.
- `rootact fence inspect --file <path> [--lines N-M]` — Ask Chesterton's Fence for a plausible reason legacy code exists before changing it.
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

## Independence from Internal

RACT is built from scratch against a public research specification for agentic coding tools. It is intentionally independent of the proprietary Internal system: no Internal code, design, or internal ideas are included. See `docs/SEPARATION.md`.

## From the author

RACT is the public, standalone expression of ideas I've been developing around assumption-driven programming, model-agnostic agentic tooling, and the Root Knot — the small identity marker that keeps a human signature inside machine-generated work.

If this line of thinking resonates with you, I explore it in more depth in my [AI Agent Playbook](https://lucasroot.pro/ai-agent-playbook-thanks). The first chapter is free, and subscribers get early drafts, behind-the-scenes build notes, and the occasional rant about tooling that pretends to be magic.

No pressure. Use RACT however it helps you build better software.

## Contributing

We welcome contributions. Please see [`CONTRIBUTING.md`](CONTRIBUTING.md) for guidelines, including the Contributor License Agreement requirement.

## Security

If you discover a security vulnerability in RACT, please email **info@lucasroot.com** rather than opening a public issue. See [`SECURITY.md`](SECURITY.md) for the full policy.

## License

RACT is licensed under the **PolyForm Noncommercial License 1.0.0** — free for personal use, research, education, and noncommercial organizations.

Commercial use requires a separate license agreement. See [`COMMERCIAL.md`](COMMERCIAL.md) for details, or email info@lucasroot.com.

Copyright 2026 Dr. Lucas Root, Ph.D.

<!-- RACT 0.1.0 - Initial Public Release -->
