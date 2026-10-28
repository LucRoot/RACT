# Handoff

For a person or an agent who picks up this repository cold. It states how the code is organized, how to run it and test it, the rules that keep it safe, what v0.6 has and has not got, and how a coordinated team works on it. It points to the longer documents and does not copy them. Written for a ten-minute read.

## 1. Resume in ten minutes

1. Read `README.md` (what RACT is) and `docs/PHILOSOPHY.md` (why it is built this way: results carry assumptions and provenance, and the environment decides when work is done, whatever the model says).
2. Read section 5 here (the security rules), then `docs/THREAT_MODEL.md`.
3. Run the focused tests for the area you will touch (section 3) and the fake model server (section 3), so you see the product work before you change it.
4. If a team is working, read its coordination folder (kept outside git; the person who started you gives its location): the generated state page, the board for your lane, and the guidance addressed to you. A re-grounding pack for your role is generated from those and is the first thing to paste into a session that lost its context.
5. The v0.6 plan is `docs/ROADMAP_V0.6_AGENTIC.md`. This file does not repeat it.

## 2. Architecture map

RACT is a Python 3.11+ terminal coding agent. A Manager plans, an Executor runs one plan step at a time inside its own git worktree, and a Harness decides whether a step is done. Everything user-visible is reported as events and drawn by a renderer.

| Area | Where | What it does |
|---|---|---|
| Entry points | `cli.py`, `cli_help.py`, `headless.py`, `repl.py`, `tui.py` | The `ract` command and its verbs; `ract -p` for scripts and CI; the interactive session; the Rich console. |
| Session turns | `session_turn.py`, `session_events.py`, `session_render.py`, `turn_context.py`, `turn_summary.py` | One interactive turn runs on a worker thread and is reported as ordered events (`docs/EVENTS_SESSION.md`); the plain renderer draws them; the turn summary holds facts the harness observed. |
| Planning | `manager.py`, `plan_validator.py`, `planner.py`, `default_prompts/manager.txt` | Turns an intent into a plan of steps with an assumption and a confidence. The prompt text has a golden test. |
| Running a plan | `ract_runner.py`, `harness.py`, `loop_controller.py`, `executor/` | `run_ract` is the one-shot path; `Harness` builds the run; `executor/` holds steps, the worktree-per-step substrate, process groups and the tool gate. |
| Writing files safely | `write_gate.py`, `undo_backup.py`, `diff_applier.py`, `workspace_path.py`, `session_rollback.py` | The write gate refuses to replace a file with something that is not that file; every replaced file's previous bytes are kept per turn (state directory) for `/undo`; the path resolver is the single place that decides what path a value may name. |
| Providers | `providers/`, `provider_presets.py`, `retry_policy.py`, `model_output.py`, `tool_calls.py`, `config_check.py`, `doctor.py` | Adapters (`openai`, `openai_compatible`, `local_http`, `local`, `internal`), presets, retries, parsing of model output and tool calls, config validation, `ract doctor`. |
| Egress | `egress_ledger.py`, `egress_scan.py`, `redaction.py` | Every HTTP client is made through the ledger, which records the destination host, sizes and tokens, never content; the scan redacts secret-shaped values from everything sent to a model; `docs/EGRESS.md` lists every outbound site. |
| Trust | `trust.py`, `hook_system.py`, `mcp_adapter.py` | A repository's own hooks, MCP servers and provider commands run only after the operator says so (`ract trust`); the store is in the user state directory, outside the workspace. |
| First run | `setup/` | `ract setup`: host and local-server probes, model-size guidance data, the wizard that writes `ract.yaml`. |
| Provenance and results | `rooted.py`, `core/`, `receipt*.py`, `provenance_*.py` | `Rooted[T]` results with assumption, confidence and provenance; Rootknot records (signing is not wired into the CLI yet; the CLI says so on every run). |
| Memory and retrieval | `memory/`, `memory_arena.py`, `codebase_historian.py`, `retrieval_adapter.py` | Indexes of the repository, session memory, optional web retrieval. |
| Safety checks | `security/`, `safety_guardrails.py`, `load_bearing_guard.py`, `duplication_guard.py`, `antilazy/` | Sandbox descriptions, the guards a step passes before a write lands, the anti-lazy gates. |
| Tools | `tools/`, `tools/read.py`, `tools/loop.py`, `executor/tool_gate.py` | Tool specs and `run_tool` (ADR-0047); the tier-0 read tools (`read_file`, `list_dir`, `glob`, `grep`); the loop an answer step uses to call them, each call through the tool gate. |
| Plan approval | `plan_gate.py`, `approval_callback.py` | ADR-0049 D12: in `default` mode a plan that changes files is approved, skipped step by step or cancelled once, before the first step. |
| Release surface | `source_digest.py`, `dead_code_auction.py` | A hash over the shipped source (re-lock in every commit that changes `src/ract/`); a test that finds modules nothing uses. |

Two event streams exist and are kept separate: the session stream (`docs/EVENTS_SESSION.md`, what a person or a script sees) and the trace log (`docs/EVENTS.md`, the audit record). A drift guard in `tests/trace/` checks that every emitted kind is registered on the right side.

## 3. Running things

- **Focused tests**: `python -m pytest <paths> -q -p no:cacheprovider`. Always include the neighbours of what you change, `tests/security/`, `tests/trace/`, and the release-surface set: `tests/test_public_provenance.py tests/test_use_cases_catalog.py tests/test_source_digest.py tests/test_release_surface.py tests/unit/test_readme_verb_index_matches_parser.py`.
- **Commit gate**: `python scripts/ci_parity.py` (lint, type checks for Linux and macOS platforms, the checks CI runs).
- **Full suite**: `python -m pytest -q -p no:cacheprovider --ignore=tests/memory`, in a throwaway git worktree, alone on the machine. It takes 30 to 40 minutes on a quiet machine and several times that on a loaded one.
- **Fake model server**: `python -m tests.fixtures.fake_model_server --scenario <name> --verbose` prints a URL; scenarios are JSON files in `tests/fixtures/scenarios/` (streaming, tool calls, reasoning text, truncation, 429 and 5xx faults, stalls). Point a `local_http` provider in `ract.yaml` at the URL.
- **Real-terminal walkthroughs**: `python -m tests.ux.run_baseline --out <folder> --only J3,J4` drives the real `ract` in a pseudo-terminal (ConPTY on Windows, `pty` elsewhere) and saves transcripts and timings. The journeys are defined in the coordination folder's `UX_BAR.md` and recorded under `docs/ux/`. A unit test with a mocked `input()` is not a walkthrough.
- **Known flaky under load**: tests that assert a time limit (Ctrl-C returns in under 2 s; next request under 1 s) and a few in `tests/memory` (excluded from the gate). A timing test asserts its limit under load and its target only when the machine is quiet. When a test fails, run it alone before changing anything.
- Do not run focused sets while a full run is in progress; they disturb the timing tests.

## 4. Conventions

- Results use `Rooted[T]`; an error carries a hint that says what to change.
- A commit that changes `src/ract/` re-locks the digest (`ract source-digest --lock`). A new import needs the allowlist entry in `tests/test_public_provenance.py`. A module that runs a subprocess needs a tool-gate exemption with a reason in `executor/tool_gate.py`. A module nothing calls yet needs a dead-code allowlist entry with the reason.
- A new CLI verb is registered in four places: `CLI_VERBS`, `cli_help.py`, `docs/USE_CASES.jsonl` and the README verb index; the README stays under its word cap.
- A new emitted event kind is registered for the drift guard; search the tests for assertions that the kind never appears.
- Write patch scripts to files and run them; do not paste escaped heredocs into a shell.
- Author and committer are only the repository owner. No AI attribution in any commit or file. No em-dashes and no "not this, that" phrasing in documents or user-facing text. No private project names, endpoints or ports in tracked files. Commits are small, with a message that says what the code does and what was run.
- Nothing is pushed, tagged or published except by the owner's explicit command.

## 5. Security rules

- **Nothing in the workspace is trusted.** A cloned repository can ship any file under `.ract/` and any config. Every reader of such a file treats it as hostile input: containment checks on every path (`undo_backup.check_entry`, `require_name`), size caps, no value from a file used as a command or an unchecked path, text from files made inert before display (`session_events.safe_text`).
- **Keys.** An API key from the environment is sent only to hosts paired with that variable outside the project; a repository cannot add a pair. Nothing prints a key, and the outbound scan redacts secret-shaped values.
- **Repository-supplied execution** (hooks, MCP servers, provider commands, coverage and mutation gates, web retrieval) runs only after `ract trust`; headless runs load none of it unless `--trust-project` is given.
- **No hidden activity.** `/cost` and `ract doctor --egress` list every request that leaves the machine, by purpose.
- **No model output can approve a tier-2 or tier-3 action.** Only the harness writes the verdict.
- **Tier 3 is off by default** and is never loosened by a code change.
- **Defects in the published v0.5.2 that the current line fixes**: a repository's hooks, MCP servers and provider commands ran with no prompt; the API key could be sent to any host the repository named; a plan step that read a file could overwrite it with the model's reply; four code paths (rollback, consolidate apply, consolidate rollback, session import) wrote files from paths named inside repository-supplied data. Each fix has regression tests that failed before it.

## 6. State of v0.6

The shell (session events, renderer, interrupts, headless mode, `/cost`, `/undo`, first-run setup, the turn summary, ask mode, repository trust, the egress ledger) is built and walked through against a scripted model. Plan approval (ADR-0049 D12) and the read-only tool slice (`read_file`, `list_dir`, `glob`, `grep` and the loop an answer step uses) are built; the slice still needs its Linux run of the path and link cases. What is not built: the tool layer beyond that slice, native tool calling per provider, command execution, git tools, per-hunk diff review, signing in the CLI, the role loader, Linux and macOS evidence, and any run against a real model. Release readiness is tracked in the coordination folder as a scorecard; v0.6.0 is not release-ready, and `VERSION` stays at the last published number until the owner says otherwise.

## 7. Working as a team

Several agents can work in parallel under a manager and a senior builder.

- Each worker has its own git worktree in a sibling folder and branches named `work/<name>/<card-id>`; workers never edit the main checkout or check out the integration branch.
- A worker logs `READY <hash>`; the senior builder reviews the diff and lands it by cherry-pick at fixed times each hour, keeping the worker's message and author. A card that does not pass is returned with reasons.
- A marker file in the coordination folder (`QUIET.md`) exists while a full-suite or Linux run owns the machine; nobody else runs tests then.
- Some areas are senior-only (path handling and any reader of workspace files, the trust store, key handling, egress, tiers, signing and events, the digest and allowlist rules, the sandbox, harness gates, the planner prompt, the config schema, session modes and undo, the security tests, release files). A worker who thinks a card needs a change there stops and asks.
- Cards are small (about two hours) and say what the user sees when done, which files may change, which tests are needed, how to run it for real and when to stop and ask.
- A full history of decisions is in the coordination folder's `DECISIONS.md`.
