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
./scripts/install.sh --local --venv        # creates ./.venv
source .venv/bin/activate
```

On Debian, Ubuntu and other systems that mark the system Python as externally
managed (PEP 668), a plain `pip install` fails. Use `--venv` as above, or
`--venv /path/to/dir` to choose the location.

Verify the installation:

```bash
ract --version
ract --help
```

The CLI will greet you with a short tagline. If you are on macOS, enjoy the same wheel without the fan noise.


## Work inside a session

Run `ract` with no arguments in a terminal to open an interactive session. Type an
intent and press Enter. Lines that start with `/` are commands. For a screen reader
or a log file, add `--plain` (or set `TERM=dumb`): no color, no boxes, and each
line labeled `you:` or `ract:`. A walkthrough of a session, from captured runs, is in
[SESSION_GUIDE.md](SESSION_GUIDE.md).

```text
$ ract
ract> add input validation to the login endpoint
ract> /plan split the config loader into two modules
ract> /set stream on
ract> /doctor --check-providers
ract> /exit
```

| Command | What it does |
|---------|--------------|
| `<text>` or `/run <intent>` | Plan and execute the intent. |
| `/plan <intent>` | Plan only. Nothing is written. |
| `/ask <question>` | Answer a question. No plan, and nothing is written. |
| `/cost [--by purpose\|step\|role]` | Requests, tokens and bytes this session sent off the machine; `--by` groups the model requests by purpose, plan step or role. |
| `/mode plan\|default\|auto-accept` | `plan` proposes and writes nothing; `default` (the starting mode) asks before each change; `auto-accept` applies changes without asking. The mode is in the status line. |
| `/undo`, `/redo` | Reverse the last turn's file changes, or the last undo. |
| `/checkpoint`, `/restore N` | List the checkpoints, numbered, newest first; go back to checkpoint N by reversing every later turn, newest first. A file you changed since is skipped and named, and the walk stops there. |
| `/review` | Go through the last turn's changes hunk by hunk: `a` accept, `r` reject (the turn's saved copy of that hunk comes back), `e` edit, `s` skip, `A` or `R` for the rest of the file. `/undo` still reverses the whole turn afterwards. |
| `/loop <intent>` | Run the quality-anchored loop. |
| `/set dry-run\|stream\|auto on\|off` | Change how turns run. `/set mode` and `/set iterations` also work. |
| `/settings`, `/session [new\|id]` | Show settings, or restart or switch the session that carries context. |
| `/providers`, `/config`, `/doctor`, `/report` | Inspect the setup and the last run. |
| `/<verb>` | Any other RACT verb, for example `/whisper` or `/fence`. |

Each turn after the first resumes the same session, so a follow-up like "now add a test for
it" has the earlier work as context.

Known limits in this release: Ctrl-C at the prompt clears the line, but Ctrl-C during a
running turn takes effect only when the turn ends. Line history and tab completion work on
Linux and macOS, where Python has `readline`; on Windows the session has neither yet.
Ctrl-D or `/exit` leaves. Scripts and CI use `ract -p '<intent>' --accept-edits`, or `ract run '<intent>' --yolo`: with no terminal to ask, a run without one of those flags does not change files.

## Set up a project

In the directory you want to work in:

```bash
ract setup
```

Setup checks the machine (memory, disk, git), looks for a model server
already running on its default port, and otherwise asks local or cloud. It
asks at most four questions in the common path, writes `ract.yaml` and
`prompts/manager.txt`, runs one tiny request to prove the config works, and
prints what to run next. It never downloads a model and never asks for an
API key: the config refers to the key's environment variable. An existing
`ract.yaml` is never overwritten; `ract setup --reconfigure` writes
`ract.yaml.draft` and shows the difference.

| Situation | Command |
|---|---|
| No terminal (CI, scripts) | `ract setup --answers answers.yaml` |
| Answers template | `ract setup --print-defaults` |
| Take every default | `ract setup --yolo` |

## Scaffold your first project

To start from a built-in template instead:

```bash
ract init --template python-package --provider local
```

This creates `ract.yaml`, `prompts/manager.txt`, starter source under `src/`,
tests, a `README.md`, and a built-in skill. You can also use `--provider openai`,
`--provider glm`, or any other preset.

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
