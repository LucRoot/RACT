# Rooted by Dr. Lucas Root, Ph.D.

# RACT Quickstart Guide

RACT (Root Agentic Coding Tool) gets you from installation to your first agentic coding run in a few minutes.

## What you need

- Python 3.11 or newer
- An LLM endpoint (local or remote). RACT is model-agnostic.

## Install RACT

RACT ships as a pure-Python wheel and runs on Windows, macOS, and Linux.

### macOS / Linux (one-line)

```bash
curl -sSL https://raw.githubusercontent.com/LucRoot/RACT/main/scripts/install.sh | bash
```

### Any platform (pip)

```bash
pip install ract
```

### From source

```bash
git clone <repository> RACT
cd RACT
./scripts/install.sh --local --venv
```

Verify the installation:

```bash
ract --version
ract --help
```

The CLI will greet you with a short tagline. If you are on macOS, enjoy the same wheel without the fan noise.


## Scaffold your first project

The fastest way to start is with a built-in template:

```bash
ract init --template python-package --provider local
```

This creates `ract.yaml`, `prompts/manager.txt`, starter source under `src/`,
tests, a `README.md`, and a built-in skill. You can also use `--provider openai`,
`--provider moonshot`, or any other preset.

## Create your first project manually

If you prefer to set up by hand, create a project directory and add a configuration file:

```bash
mkdir my_project
cd my_project
```

Create `ract.yaml`:

```yaml
project:
  name: my_project

manager_provider: local

providers:
  local:
    adapter: local_http
    url: http://127.0.0.1:11434/v1
    model: my-local-model

context_budget_tokens: 4096
```

If you are using a remote OpenAI-compatible API, use the `openai` adapter instead:

```yaml
providers:
  openai:
    adapter: openai
    url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    model: gpt-4o-mini
```

See `PROVIDER_SETUP.md` for more provider configurations.

## Run your first task

```bash
ract run "write a hello-world Python script" --config ract.yaml
```

RACT will:

1. Load the configuration.
2. Curate project context within the token budget.
3. Ask the manager model to produce a plan.
4. Execute each step through the configured provider.
5. Print the results and a quality score.

## Dry-run a plan

To see the plan without executing it:

```bash
ract run "add a test for the hello-world script" --config ract.yaml --dry-run
```

The output includes the assumption, confidence, steps, and quality score.

## Use a session

Sessions let RACT remember prior work across runs.

```bash
ract run "write a hello-world Python script" --config ract.yaml --session demo
ract run "add a test for it" --config ract.yaml --session demo --resume
```

The second call loads the memory arena from the first run and prepends a replay block to the prompt.

## Use a project document

Create `project.json`:

```json
{
  "goal": "Build a small CLI greeting tool",
  "notes": ["Use argparse", "Keep it under 100 lines"]
}
```

Then run:

```bash
ract run "implement the greeting tool" --config ract.yaml --project-doc project.json
```

## Run modes

- **default**: normal execution.
- **documentation**: rewrite the intent to prioritize docs before code.
- **git**: stage and commit produced artifacts after a successful run.

```bash
ract run "document the greeting tool" --config ract.yaml --mode documentation
ract run "commit the greeting tool" --config ract.yaml --mode git
```

## Other useful commands

- `ract --welcome` — show the branded Root-Knot welcome screen.
- `ract report --last` / `--session ID` — view a structured run summary.
- `ract handshakes list/approve/reject/defer` — review high-risk milestones the loop deferred.
- `ract mcp list` — inspect tools exposed by configured MCP servers.
- `ract retrieval search <query>` — preview what context RACT retrieves before planning.
- `ract diff apply --patch <path> [--dry-run]` — apply a unified-diff patch surgically.
- `ract novelty scan [--json]` — preview compression-based novelty scores (local, no model call).
- `ract whisper --intent "..."` — get a Legacy Whisperer dialect/history brief.
- `ract auction list [--min-age-days N]` — review old, unreferenced modules.
- `ract fence inspect --file <path>` — ask Chesterton's Fence why legacy code exists.
- `ract load-bearing list` — list annotated load-bearing regions.
- `ract refactor --old <name> --new <name> [--dry-run]` — AST-guided symbol rename.
- `ract openapi generate-client|generate-server --spec <path> --output <path>` — OpenAPI generators.
- `ract plan export --session <id> --output <path>` / `replay --plan <path>` — deterministic plan replay.
- `ract doctor [--check-providers]` — run config and project diagnostics.

## Run the self-recursing loop

For tasks that need multiple iterations of plan/execute/verify, use `--loop`. The loop plans milestones, executes one per iteration, runs your test command, and continues until the work is done, a regression is detected, or the iteration limit is reached.

```bash
ract run "add input validation to the login endpoint" --config ract.yaml --loop --max-iterations 10
```

If a provider call hangs, the loop enforces a per-iteration timeout (default 900s, configurable in code) and feeds the previous iteration's error, test output, and any missing Rootknot sidecars into the next prompt.

## Use built-in skills

RACT ships with signed skill templates for common tasks:

```bash
ract skills list
ract skills install python-package
ract skills install-all
```

Shipped project templates: `python-package`, `cli-tool`. Skill packages under `ract skills` are catalogued separately from the `ract init --template` project scaffolds; run `ract skills list` for the shipped skill set.

## View run reports

After a loop or single run, inspect what happened:

```bash
ract report --last --config ract.yaml
```

The report shows the final decision, summary, handshake milestones, and per-iteration test results.

## Operator handshakes

High-risk milestones (e.g., destructive operations) do not pause the loop. Instead, they are queued as handshakes for operator review:

```bash
ract handshakes list
ract handshakes approve <milestone-id>
ract handshakes reject <milestone-id>
ract handshakes defer <milestone-id>
```

## Toggles

- `--yolo`: execute without per-step approval (default).
- `--auto`: prompt for approval before each step.
- `--reload`: run the intent again after a successful first run.
- `--stream`: stream provider responses to stdout as they are generated.
- `--self-test`: run RACT's internal test suite.

## Next steps

- Read `ARCHITECTURE.md` to understand the runtime.
- Read `PROVIDER_SETUP.md` to connect your preferred LLM.
- Read `SKILL_AUTHORING.md` to create reusable skill templates.

<!-- RACT 0.1.1 - Trust and tooling -->
