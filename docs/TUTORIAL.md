# Rooted by Dr. Lucas Root, Ph.D.

# RACT Tutorial: Build a Small Library End-to-End

This tutorial walks through a complete RACT session. You will scaffold a
project, generate code, verify it, refactor it, generate documentation, and
review a run report. All steps use a local LLM, but the same commands work with
any OpenAI-compatible provider.

## What you will build

A tiny `greet` library with one function, one test, and one CLI entry point.

## Prerequisites

- Python 3.11 or newer
- RACT installed: `pip install ract`
- A local LLM server running on `http://127.0.0.1:11434/v1` (or edit the provider
  preset to match your endpoint)

## Step 1: Scaffold the project

```bash
mkdir greet-tutorial
cd greet-tutorial
ract init --template cli-tool --provider local
```

You now have:

- `ract.yaml` — project configuration and provider preset
- `prompts/manager.txt` — the manager prompt
- `src/greet-tutorial/__init__.py` and `main.py` — starter source
- `tests/test_main.py` — starter test
- `README.md` and `pyproject.toml` — project metadata
- `skills/cli-tool.json` — a built-in skill

## Step 2: Run your first intent

```bash
ract run "add a greet(name) function that returns Hello, name and add a test" --config ract.yaml
```

RACT will:

1. Load the config and manager prompt.
2. Curate the project context within the token budget.
3. Ask the manager model for a plan.
4. Execute each step through the configured provider.
5. Write generated artifacts to disk after safety and signature checks.

Inspect the results:

```bash
cat src/greet_tutorial/main.py
cat tests/test_main.py
```

## Step 3: Verify the generated code

```bash
python -m pytest -q
```

If a test fails, run the self-recursing loop so RACT can repair it:

```bash
ract run "fix the failing test" --config ract.yaml --loop --max-iterations 5
```

## Step 4: Generate API documentation

```bash
ract docs generate --config ract.yaml
```

Open `docs/api/index.md` to see Markdown docs extracted from docstrings and
signatures.

## Step 5: Refactor a symbol

Rename the `greet` function to `salute` across the project:

```bash
ract refactor --old greet --new salute --dry-run --config ract.yaml
```

Review the planned edits, then apply them:

```bash
ract refactor --old greet --new salute --config ract.yaml
```

Run the tests again to confirm nothing broke:

```bash
python -m pytest -q
```

## Step 6: Review the run report

After any loop or single run, inspect the structured report:

```bash
ract report --last --config ract.yaml
```

The report shows the final decision, summary, any pending operator handshakes,
and per-iteration outcomes.

## Step 7: Handle operator handshakes

If a high-risk milestone was queued (for example, a destructive file operation),
it appears as a handshake instead of executing immediately:

```bash
ract handshakes list
ract handshakes approve <milestone-id>
```

This keeps the loop moving while keeping you in control of dangerous actions.

## Next steps

- Read `ARCHITECTURE.md` to understand how the harness, planner, executor, and
  loop controller work together.
- Read `PROVIDER_SETUP.md` to connect RACT to OpenAI, Anthropic, Z.ai,
  Moonshot, OpenRouter, or another local server.
- Read `SKILL_AUTHORING.md` to build reusable prompt templates for your own
  workflows.

<!-- RACT 0.1.1 - Trust and tooling -->
