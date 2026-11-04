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

The prompt reads `ract>` in a normal terminal. In a plain session (`--plain`,
or `TERM=dumb`, or a screen reader) the same lines carry `you:` and `ract:`
labels instead, so a log of a plain session shows `you:` where this capture
shows `ract>`. Both are the same session.

| Command | What it does |
|---------|--------------|
| `<text>` or `/run <intent>` | Plan and execute the intent. |
| `/plan <intent>` | Plan only. Nothing is written. |
| `/ask <question>` | Answer a question. No plan, and nothing is written. |
| `/cost [--by purpose\|step\|role]` | Requests, tokens and bytes this session sent off the machine; `--by` groups the model requests by purpose, plan step or role. |
| `/mode plan\|default\|auto-accept` | `plan` proposes and writes nothing; `default` (the starting mode) asks before each change; `auto-accept` applies changes without asking. The mode is in the status line. |
| `/undo`, `/redo` | Reverse the last turn's file changes, or the last undo. |
| `/checkpoint`, `/restore N` | List the checkpoints, numbered, newest first; go back to checkpoint N by reversing every later turn, newest first. A file you changed since is skipped and named, and the walk stops there. |
| `/rewind` | The turns that changed files, by what you asked, numbered; type a number to go back to that turn, Enter to keep everything. Esc Esc at the prompt runs it where the prompt uses readline (not in the Windows console, where Esc clears the line). |
| `/review` | Go through the last turn's changes hunk by hunk: `a` accept, `r` reject (the turn's saved copy of that hunk comes back), `e` edit, `s` skip, `A` or `R` for the rest of the file. `/undo` still reverses the whole turn afterwards. |
| `/loop <intent>` | Run the quality-anchored loop. |
| `/set dry-run\|stream on\|off` | Change how turns run. `/set task` and `/set iterations` also work. File changes are set with `/mode`, tier-3 commands with `/permissions ask\|allowlist`. |
| `/settings`, `/session [new\|id]` | Show settings, or restart or switch the session that carries context. |
| `/model [name]` | Show the configured models, or switch the manager for this session. |
| `/diff` | Show the last turn's changes, from the copies it saved. |
| `/context` | What the last request sent, and the room the model has. |
| `/sessions`, `/resume <id\|latest>` | List recent sessions (id, time, turns, cost, last request), or switch to one and show its last request. |
| `/queue [drop <n>]` | List the lines typed during a turn; `drop <n>` withdraws one. |
| `/permissions [ask\|allowlist]` | Show what RACT may change or send, in one screen; `ask` and `allowlist` set the tier-3 mode, up to the grant's largest mode. |
| `/clear`, `/help` | Clear the screen, or show the list of commands. |
| `/providers`, `/config`, `/doctor`, `/report` | Inspect the setup and the last run. |
| `/<verb>` | Any other RACT verb, for example `/whisper` or `/fence`. |

Each turn after the first resumes the same session, so a follow-up like "now add a test for
it" has the earlier work as context.

No shell escape: RACT has no `!command` prefix. The model proposes commands and you
approve them at the ask screen (see "Let RACT run your tests" below for the one command
that matters most).

Project instructions: RACT reads the project's small text files into the request
context — README first, and any `.md` file at the top level (so a file named
`AGENTS.md`, `CLAUDE.md`, or `ract.md` works; keep them short and plain).

Fetching web pages is a tier-3 tool (see `docs/TIER3.md`): it asks before every fetch,
only over https, and only to domains a grant names; with no grant it never runs.

Known limits in this release: Ctrl-C at the prompt clears the line, but Ctrl-C during a
running turn takes effect only when the turn ends. Line history and tab completion work on
Linux and macOS, where Python has `readline`; on Windows the session has neither yet.
Ctrl-D or `/exit` leaves. Scripts and CI use `ract -p '<intent>' --accept-edits`, or `ract run '<intent>' --yolo`: with no terminal to ask, a run without one of those flags does not change files.

## Let RACT run your tests

RACT can run your tests when you ask, for example with `/test` in a session
or when the model needs them. Setup asks once at the end (say yes, or run
`ract policy init --guided` later). What RACT prints:

```text
One more thing. RACT can run your tests when you ask, for example with
/test in a session or when the model needs them. It would run one command,
the test runner this setup found.
Let RACT run your tests when you ask? [Y/n]
```

The grant names one command. The network stays off where this machine can
enforce it, each run has a time limit, and you can take it back any time:
`ract policy revoke`. In a session, `/test` runs the granted command and
shows the result; the next turn can act on a failure.

One honest limit: in a session the model cannot run your tests by itself.
RACT's loop (`/loop`) runs your test command, and tier 3 lets a signed
grant run commands under your rules; the model can also tell you the command
to run.

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
To add a second endpoint to an existing `ract.yaml`, run `ract setup --add-provider`:
the same questions, the difference shown before anything is written, the same one-request
check on the new provider, and the manager provider left as it is. `ract doctor
--check-providers` then checks every provider in the file.

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

The second call resumes the session: the stored intent is the one that runs (an intent typed on the command line is not used), and the run opens with a short summary of the prior outcomes and artifacts.

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
  Git mode is off until you enable it: add `git_mode: true` to ract.yaml.

```bash
ract run "document the greeting tool" --config ract.yaml --mode documentation
ract run "commit the greeting tool" --config ract.yaml --mode git
```

## Other useful commands

- `ract --welcome`: show the branded Root-Knot welcome screen.
- `ract report --last` / `--session ID`, view a structured run summary.
- `ract handshakes list/approve/reject/defer`: review high-risk milestones the loop deferred.
- `ract mcp list`: inspect tools exposed by configured MCP servers.
- `ract retrieval search <query>`: preview what context RACT retrieves before planning.
- `ract diff apply --patch <path> [--dry-run]`: apply a unified-diff patch surgically.
- `ract novelty scan [--json]`: preview compression-based novelty scores (local, no model call).
- `ract whisper --intent "..."`: get a Legacy Whisperer dialect/history brief.
- `ract auction list [--min-age-days N]`: review old, unreferenced modules.
- `ract fence inspect --file <path>`: ask Chesterton's Fence why legacy code exists.
- `ract load-bearing list`: list annotated load-bearing regions.
- `ract refactor --old <name> --new <name> [--dry-run]`: AST-guided symbol rename.
- `ract openapi generate-client|generate-server --spec <path> --output <path>`: OpenAPI generators.
- `ract plan export --session <id> --output <path>` / `replay --plan <path>`, deterministic plan replay.
- `ract doctor [--check-providers]`: run config and project diagnostics.

## Run the self-recursing loop

For tasks that need multiple iterations of plan/execute/verify, use `--loop`. The loop plans milestones, executes one per iteration, runs your test command, and continues until the work is done, a regression is detected, or the iteration limit is reached.

```bash
ract run "add input validation to the login endpoint" --config ract.yaml --loop --yolo --max-iterations 10
```

If a provider call hangs, the loop enforces a per-iteration timeout (default 900s, configurable in code) and feeds the previous iteration's error, test output, and any missing Rootknot sidecars into the next prompt.

## Use built-in skills

RACT ships skill templates for common tasks (they are not signed):

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

- `--yolo`: execute without per-step approval (off by default; `--loop` refuses to run without it).
- `--auto`: prompt for approval before each step.
- `--reload`: run the intent again after a successful first run.
- `--stream`: stream provider responses to stdout as they are generated.
- `--self-test`: run RACT's internal test suite.

## Next steps

- Read `ARCHITECTURE.md` to understand the runtime.
- Read `PROVIDER_SETUP.md` to connect your preferred LLM.
- Read `SKILL_AUTHORING.md` to create reusable skill templates.

<!-- RACT 0.1.1 - Trust and tooling -->
