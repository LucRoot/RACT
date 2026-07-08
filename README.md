# RACT (Root Agentic Coding Tool)

<p align="center">
  <img src="https://raw.githubusercontent.com/LucRoot/RACT/main/assets/DrLucasRoot-Logo.png" alt="Dr. Lucas Root logo" width="180">
</p>

An Agentic Coding Tool built around a small management LM, by **Dr. Lucas Root, Ph.D.**

RACT keeps the human in the loop while letting a lightweight core manager route work to the right LLM provider. Every operation is anchored to the assumption that justifies it through the `Rooted[T]` signature quirk.

> **From Dr. Root:** If RACT resonates with you, I write about the deeper philosophy behind assumption-driven programming and human-AI collaboration in my [AI Agent Playbook](https://lucasroot.pro/ai-agent-playbook-thanks). The first chapter is free.

For a hands-on introduction, see `docs/QUICKSTART.md`. For a complete walkthrough from project scaffold to run report, see `docs/TUTORIAL.md`.

## Install

RACT ships as a pure-Python wheel, so the same package runs on Windows, macOS, and Linux.

### One-line install (macOS / Linux)

```bash
curl -sSL https://raw.githubusercontent.com/LucRoot/RACT/main/scripts/install.sh | bash
```

The script detects your Python, optionally creates a virtual environment, and installs RACT from PyPI.

### Windows (where the Root Knot is forged)

```powershell
pip install rootact
```

### macOS

```bash
pip install rootact
```

Same wheel, no fan noise.

### From source

```bash
git clone https://github.com/LucRoot/RACT.git
cd ract
./scripts/install.sh --local --venv
```

Or, if you prefer pip directly:

```bash
pip install -e ".[dev]"
```

## Quick Start

Scaffold a complete project in one command:

```bash
rootact init --template python-package --provider local
```

Or create only a provider preset:

```bash
rootact --init-provider local
```

Or pick a cheap frontier provider:

```bash
rootact --init-provider zai
rootact --init-provider moonshot
rootact --init-provider openai
rootact --init-provider anthropic
rootact --init-provider openrouter
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

The loop stops when the work is done, a regression is detected (tests fail, quality drops, or the Root Knot sentinel is missing), or the maximum number of iterations is reached. Each iteration is bounded by a configurable timeout so a hung provider cannot stall the loop, and the previous iteration's error, test output, and missing-knot files are fed back into the next prompt.

### Terminal experience

RACT is terminal-first. Run `ract --welcome` to see the Root-Knot logo and a quick-command panel. User input is highlighted in cyan, direct system-to-user messages in orchid, and listing commands render as rich tables. Set `NO_COLOR=1` to disable styling.

## CLI Highlights

- `--dry-run` — Plan only; see the proposed steps and quality score.
- `--yolo` / `--auto` — Execute without prompts or require approval per step.
- `--reload` — Re-run the intent once after a successful execution.
- `--loop` — Run in the Root-Knot-anchored recursion loop with milestone tracking.
- `--max-iterations N` — Cap the recursion loop.
- `--mode {default,documentation,git}` — Switch between normal coding, documentation generation, and git-assist modes.
- `--session SESSION_ID` — Save and resume long-running sessions with rollback support.
- `--project-doc PATH` — Load a project document that prepends goal and constraints to every intent.
- `--self-test` — Run RACT's internal test suite.
- `--review-diff PATH` — Review a unified diff.
- `--stream` — Stream provider responses to stdout.
- `--init-provider {local,openai,anthropic,zai,moonshot,openrouter}` — Write a starter `rootact.yaml`.
- `ract skills list/install/install-all` — Manage built-in skill templates.
- `ract report --last` / `--session ID` — View a structured summary of the last run or session.
- `ract report --last --format json --output report.json` — Export a structured run report for scripts or CI.
- `ract handshakes list/approve/reject/defer` — Review high-risk milestones that the loop deferred.
- `ract mcp list` — Inspect tools exposed by configured MCP servers.
- `ract retrieval search <query>` — Preview what context RACT retrieves for a query.
- `ract diff apply --patch <path> [--dry-run]` — Apply a unified-diff patch file surgically.
- `ract explain --intent <text>` / `--plan <path>` — Preview a dry-run plan in plain language.
- `ract novelty scan [--json]` — Preview compression-based novelty scores for project files (local, no model call).
- `ract whisper --intent "..."` — Ask the Legacy Whisperer for a pre-planning dialect/history brief.
- `ract auction list [--min-age-days N] [--json]` — Review old, unreferenced modules proposed for deletion.
- `ract fence inspect --file <path> [--lines N-M]` — Ask Chesterton's Fence for a plausible reason legacy code exists before changing it.
- `ract --about` — Show authorship, license, and Root Knot statement.
- `ract --welcome` — Print the branded Root-Knot welcome letter.
- `ract init --template <name> --provider <name>` — Scaffold a new project from a template.
- `ract docs generate` — Generate Markdown API docs from source docstrings.
- `ract refactor --old <name> --new <name>` — Safely rename a module-level symbol across files.
- `ract openapi generate-client --spec <path> --output <path>` — Generate an `httpx`-based Python client from an OpenAPI 3 spec.
- `ract openapi generate-server --spec <path> --output <path>` — Generate a FastAPI server module from an OpenAPI 3 spec.
- `ract plan export --session <id> --output <path>` — Save a session plan to JSON for reproducibility.
- `ract plan replay --plan <path> --dry-run` — Replay a saved plan and report per-step success.
- `ract doctor [--check-providers]` — Run config diagnostics and optionally ping each provider endpoint.

## Built-in Skills

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

See `docs/ARCHITECTURE.md`, `docs/PHILOSOPHY.md`, and the research artifacts in `_BUILD/`.

## Competitive Highlights

To close gaps with Cursor, Claude Code, Lovable, and other frontier agentic tools, RACT includes:

1. **Progress Oracle** — milestone-driven recursion instead of time-based looping.
2. **Signature Survival** — golden hash + Root Knot re-injection so the author's identity persists.
3. **Provider Presets** — one-command setup for local and cheap frontier providers.
4. **Built-in Skill Library** — 7 signed templates installable from the CLI.
5. **Run Report** — `ract report --last` shows what changed, what passed, and what's pending; `--format json --output <path>` exports it for scripts or CI.
6. **Operator Handshake** — high-risk milestones queue for review instead of blocking the loop.
7. **MCP Integration** — call external tools (filesystem, database, browser, docs) from plan steps.
8. **DiffApplier** — apply surgical unified diffs to existing files instead of rewriting them whole. `ract diff apply` exposes this for manual patch files.
9. **Retrieval** — keyword retrieval surfaces relevant project files; web-search adapter supports Serper, Brave, Bing, and generic search APIs. `ract retrieval search` previews retrieved context.
10. **Compression Novelty Detector** — local information-theoretic signal that flags duplication (low novelty) and genuine outliers (high novelty) without a model call. `ract novelty scan` exposes it for operators.
11. **Legacy Whisperer** — pre-planning subagent that reads the project's symbol graph and git history, then produces a dialect/history brief so the model writes code that matches the codebase instead of generic code. `ract whisper` exposes it for operators.
12. **Dead Code Auction** — finds old modules with no inbound references and proposes them for deletion. `ract auction list` exposes the list; nothing is deleted without operator approval.
13. **Chesterton's Fence** — before removing legacy code, reads blame/history and produces a plausible reason the code exists. `ract fence inspect` exposes it for operators.

### Retrieval Example

Add a retrieval adapter to `rootact.yaml`:

```yaml
retrieval:
  adapter: keyword
  top_k: 5
  extensions: [".py", ".md"]
```

`Harness.run` will search project files for the intent keywords and prepend the top snippets to the Manager prompt.

For web search (Serper example):

```yaml
retrieval:
  adapter: web
  top_k: 3
  api_key: ${SERPER_API_KEY}
  endpoint: https://google.serper.dev/search
```

### MCP Example

Add an MCP server to `rootact.yaml`:

```yaml
mcp_servers:
  filesystem:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
```

The Manager will see the available tools in its system prompt and can emit plans like:

```json
{
  "steps": [
    {
      "action": "list project files",
      "provider_hint": "mcp",
      "expected_artifact": "",
      "tool_call": {"name": "filesystem/list_directory", "arguments": {"path": "."}}
    }
  ]
}
```

## Coder's Signature

Every non-init Python file carries three identity markers:

```python
__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
```

The `_ROOT_KNOT` sentinel is not just a signature — it is a loop invariant. If the recursion loop ever produces an artifact without the knot, the loop stops immediately rather than compounding unsigned work.

## Independence from Internal

RACT is built from scratch against a public research specification for agentic coding tools. It is intentionally independent of the proprietary Internal system: no Internal code, design, or internal ideas are included. See `docs/SEPARATION.md`.

## From the Author

RACT is the public, standalone expression of ideas I've been developing around assumption-driven programming, model-agnostic agentic tooling, and what I call the Root Knot — the small identity marker that keeps a human signature inside machine-generated work.

If you want the longer-form thinking behind RACT — including how to design agentic systems that stay accountable, auditable, and genuinely useful — I share that in my [AI Agent Playbook](https://lucasroot.pro/ai-agent-playbook-thanks). The first chapter is free, and subscribers get early drafts, behind-the-scenes build notes, and the occasional rant about tooling that pretends to be magic.

No pressure. Use RACT however it helps you build better software.

## License

RACT is licensed under the **PolyForm Noncommercial License 1.0.0** — free for personal use, research, education, and noncommercial organizations.

Commercial use requires a separate license agreement. See [`COMMERCIAL.md`](COMMERCIAL.md) for details, or email info@lucasroot.com.

Copyright 2026 Dr. Lucas Root, Ph.D.
