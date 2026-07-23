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
pip install rootact
```

### From source

```bash
git clone <repository> RACT
cd RACT
./scripts/install.sh --local --venv
```

Verify the installation:

```bash
rootact --version
rootact --help
```

The CLI will greet you with a short tagline. If you are on macOS, enjoy the same wheel without the fan noise.


## Scaffold your first project

The fastest way to start is with a built-in template:

```bash
rootact init --template python-package --provider local
```

This creates `rootact.yaml`, `prompts/manager.txt`, starter source under `src/`,
tests, a `README.md`, and a built-in skill. You can also use `--provider openai`,
`--provider moonshot`, or any other preset.

## Create your first project manually

If you prefer to set up by hand, create a project directory and add a configuration file:

```bash
mkdir my_project
cd my_project
```

Create `rootact.yaml`:

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
rootact "write a hello-world Python script" --config rootact.yaml
```

RootAct will:

1. Load the configuration.
2. Curate project context within the token budget.
3. Ask the manager model to produce a plan.
4. Execute each step through the configured provider.
5. Print the results and a quality score.

## Dry-run a plan

To see the plan without executing it:

```bash
rootact "add a test for the hello-world script" --config rootact.yaml --dry-run
```

The output includes the assumption, confidence, steps, and quality score.

## Use a session

Sessions let RootAct remember prior work across runs.

```bash
rootact "write a hello-world Python script" --config rootact.yaml --session demo
rootact "add a test for it" --config rootact.yaml --session demo --resume
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
rootact "implement the greeting tool" --config rootact.yaml --project-doc project.json
```

## Run modes

- **default**: normal execution.
- **documentation**: rewrite the intent to prioritize docs before code.
- **git**: stage and commit produced artifacts after a successful run.

```bash
rootact "document the greeting tool" --config rootact.yaml --mode documentation
rootact "commit the greeting tool" --config rootact.yaml --mode git
```

## Other useful commands

- `rootact --welcome` — show the branded Root-Koot welcome screen.
- `rootact report --last` / `--session ID` — view a structured run summary.
- `rootact handshakes list/approve/reject/defer` — review high-risk milestones the loop deferred.
- `rootact mcp list` — inspect tools exposed by configured MCP servers.
- `rootact retrieval search <query>` — preview what context RACT retrieves before planning.
- `rootact diff apply --patch <path> [--dry-run]` — apply a unified-diff patch surgically.
- `rootact novelty scan [--json]` — preview compression-based novelty scores (local, no model call).
- `rootact whisper --intent "..."` — get a Legacy Whisperer dialect/history brief.
- `rootact auction list [--min-age-days N]` — review old, unreferenced modules.
- `rootact fence inspect --file <path>` — ask Chesterton's Fence why legacy code exists.
- `rootact load-bearing list` — list annotated load-bearing regions.
- `rootact refactor --old <name> --new <name> [--dry-run]` — AST-guided symbol rename.
- `rootact openapi generate-client|generate-server --spec <path> --output <path>` — OpenAPI generators.
- `rootact plan export --session <id> --output <path>` / `replay --plan <path>` — deterministic plan replay.
- `rootact doctor [--check-providers]` — run config and project diagnostics.

## Run the self-recursing loop

For tasks that need multiple iterations of plan/execute/verify, use `--loop`. The loop plans milestones, executes one per iteration, runs your test command, and continues until the work is done, a regression is detected, or the iteration limit is reached.

```bash
rootact "add input validation to the login endpoint" --config rootact.yaml --loop --max-iterations 10
```

If a provider call hangs, the loop enforces a per-iteration timeout (default 900s, configurable in code) and feeds the previous iteration's error, test output, and any missing Root Knot files into the next prompt.

## Use built-in skills

RACT ships with signed skill templates for common tasks:

```bash
rootact skills list
rootact skills install python-package
rootact skills install-all
```

Available templates include `python-package`, `fastapi-app`, `react-component`, `test-generation`, `documentation-update`, `cli-tool`, `library-refactor`, `api-client`, `data-pipeline`, and `config-driven-service`.

## View run reports

After a loop or single run, inspect what happened:

```bash
rootact report --last --config rootact.yaml
```

The report shows the final decision, summary, handshake milestones, and per-iteration test results.

## Operator handshakes

High-risk milestones (e.g., destructive operations) do not pause the loop. Instead, they are queued as handshakes for operator review:

```bash
rootact handshakes list
rootact handshakes approve <milestone-id>
rootact handshakes reject <milestone-id>
rootact handshakes defer <milestone-id>
```

## Toggles

- `--yolo`: execute without per-step approval (default).
- `--auto`: prompt for approval before each step.
- `--reload`: run the intent again after a successful first run.
- `--stream`: stream provider responses to stdout as they are generated.
- `--self-test`: run RootAct's internal test suite.

## Next steps

- Read `ARCHITECTURE.md` to understand the runtime.
- Read `PROVIDER_SETUP.md` to connect your preferred LLM.
- Read `SKILL_AUTHORING.md` to create reusable skill templates.

<!-- RACT 0.1.1 - Trust and tooling -->
