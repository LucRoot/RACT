:warning: This file is project documentation, not part of the source code.

# Changelog

All notable changes to RACT (Root Agentic Coding Tool) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `ract verify` checks a commit range and/or a run offline (B-039, ADR-0050
  as amended by D-174): every changed line attributed to a signed step, each
  Rootknot verified, and the run's trace chain when the run has one; a run
  without a trace is reported as a fact, and every report ends with the
  statement that command records are not part of the signed Rootknot.
- The to-do tool is wired (B-177): the step agent loop offers `todo`; the harness applies its facts after the step's work ends and keeps the list at `.ract/todo.json` in the workspace; the read-only answer loop does not offer it (it has no list to apply the facts to); `/todo` shows the list with its counts.
- The guided spec is wired (B-178): `/spec` walks the six questions one at a time, keeps each answer as written, asks for approval per section (keep it, type a replacement, ask again), checks that every acceptance line names something checkable before the file is written, and saves `SPEC.md` with the SHA-256 of the approved bytes in `.ract/spec_hash.txt`; an abandoned walk keeps its draft in `.ract/spec_draft.json` and the next `/spec` continues it. The sections are drafted from the person's own words in this slice; the model-drafted redraft needs a model call and is the stated next piece.
- The fetch question uses the network screen (B-225 part 3): a `web_fetch` approval shows the host, the allowlist entry it matches, the size cap and the follows line (MASON's B-227 screen), with the same once/session/no answer flow; a command approval keeps the command screen. The fetch's facts carry the screen's fields, and the network screens' auction entry is gone (they have a caller).
- Text of unknown origin is marked in front of the model (B-149): each tool result arrives
  in a delimiter naming its origin (`file`, `command output`, `fetched page`, `search
  result`) and saying it is data, and text inside it cannot close the delimiter. A tier-2 or
  tier-3 proposal that follows a fetched page says `follows fetched page from <host>` on its
  card and always asks: an allow rule or a session answer does not run it.
- A grant rule may name `backend: wsl2` or `backend: container` (with an image pinned by
  digest, `name@sha256:...`; a tag alone is refused at load) (B-028, D-142). Such a rule
  does not run yet and is refused at run with the reason; nothing runs on this host in its
  place. `ract doctor --tier3` lists both backends and what each still needs.
- `ract doctor --tier3` reports the tier-3 state in one place (B-147): the grant (status,
  key, expiry, digest, largest mode), why tier 3 is off, the operator key and how it is
  protected, the unlock window, the sandbox as this machine runs it, the entry-point
  record, the session mode, which tier-3 tools the grant makes available, and the command
  that fixes each problem. `--json` carries the same fields.
- `ract policy init --guided` also finds the linter, type checker, formatter and build
  (ruff or flake8, mypy or pyright, ruff format or black, a Python build backend, and the
  npm scripts) and proposes the narrowest rule for each, network off and 15 minutes, in
  one diff under one signature (B-142). `ract policy add-rule ID -- ARGV...` adds one rule
  to a grant that holds, shows the diff and signs it again; a grant changed since its
  signature is refused.
- Verifier tools (B-023): `run_build`, `run_lint`, `run_typecheck` and `run_format` run the
  grant's rule for each kind (by id, or a known command such as `ruff check` or `mypy`) the
  same way `run_tests` does: tier 3, matched, asked, through `run_command`. Each result says
  the kind, the command id, the exit code, the time and the output digest. A failed real run,
  a named test included, makes the turn `failed` (exit 1) and the verdict names it.
- Allowlist mode and session approvals (B-113, ADR-0048 D4, D6): `/permissions allowlist` lets
  a command that matches an allow rule run without asking, up to the grant's `max_mode`;
  `/permissions ask` goes back. Remote git, output and execution flags, tier 2 and a changed
  test, conftest or runner or build configuration file still ask, in every mode; the entry
  points are recorded when the grant is signed, outside the project. `s` at a tier-3 question
  approves that exact command for the session (memory only; it does not carry over to
  `--resume`), and `/permissions` lists those approvals.
- Git tools (B-115, B-024, ADR-0048 D8): `git_status`, `git_diff` and `git_log` read; `git_add`,
  `git_commit`, `git_branch` and `git_worktree` ask once per call with the exact command; a
  staged secret refuses the commit and names the file and line; hooks run only under a grant
  rule with `git_hooks: true`. `git_push` needs a grant rule for it, a signed handshake for the
  remote and branch, and the operator's yes. Every git call runs with fsmonitor off, no hooks,
  no pager and no external diff.
- `web_fetch` (B-116, B-026, ADR-0048 D11): https only, to the grant's `allow_domains`, every
  redirect checked, private, loopback and metadata addresses refused after resolution, a body
  cap, HTML reduced to text, the result labeled external; `--no-network` refuses it.
  `web_search` has no provider and says so.
- On Linux, a tier-3 command runs inside bubblewrap once a self-test inside it shows that a
  write outside the workspace, a host file, the network and the host's processes are out of
  reach (B-114). `ract doctor --sandbox` says, for this machine, what confines a command and
  what does not (B-025). On Windows and macOS grants still say `best_effort`.
- The harness signs what it writes (S-015b): each file a turn changes gets a v4 Rootknot, and
  `ract provenance verify` passes on it; the turn says signed only when every changed file's
  knot verifies, and names any that does not.
- `session.started` carries the session id and the context window when the probe measured it
  or `ract.yaml` declares it; the status line shows both (B-084).
- Session modes: `/mode plan` (the planner proposes, nothing runs or is written), `/mode default`
  (RACT asks before each step that changes a file; a step that only answers is not asked
  about), `/mode auto-accept` (changes are applied without asking). The session starts in
  `default`. The mode is in the status line and comes from the same setting the approval
  uses. `unrestricted` is refused: it needs the tier-3 policy, which this release does not
  have.
- `ract -p` starts in `default` mode too. With no terminal to ask, a step that would change a
  file is refused (exit 3) and the hint names `--accept-edits`, the flag that lets the run
  change files. Answers need no flag. Scripts that let `ract -p` edit files must add
  `--accept-edits`.
- `/undo` and `/redo` in the session, `ract undo` and `ract redo` in the shell: reverse the last
  turn's file changes from its backup. Files the turn replaced are restored and files it created
  are removed; a file you changed after the turn is listed and left alone unless you pass
  `--force`. The undo keeps its own backup, so `/redo` reverses it once. Works outside a git
  repository. The backups and their manifests live in the user state directory, so a cloned
  repository cannot ship one, and every path in a manifest is checked to stay inside the
  workspace, with `--force` too; a refused entry is listed. Interim and file-level;
  checkpoints will replace it.
- The end of each turn is the harness's account, one fact per line: the verdict; what changed
  with lines added and removed (`src/calc.py (+1 -1)`); where the previous versions are; whether
  RACT ran tests; what the plan assumed, with the planner's confidence; how many model requests,
  how long and how many tokens. When the reply says tests pass (or "verified", "done and
  tested") in a turn where RACT ran none, a line says that nothing checked it. Prose after a file
  change is labelled `model summary`. `turn.finished` carries `diffstat`, `undo` and
  `verification.claims`. Line counts compare each file with its copy from before the turn, so
  your own uncommitted edits are not counted and no git repository is needed.
- `ract "<intent>" --json` prints the `ract.result/1` object, as `ract -p "<intent>"
  --output-format json` does; with run flags that path cannot take it is a usage error. Before,
  `--json` with an intent printed the human output.
- `ract setup`: first-run setup. It checks the machine, offers a model server already running on
  a default port (llama.cpp, Ollama, LM Studio, vLLM) or one named in `RACT_BASE_URL`, and
  otherwise asks local or cloud. For a local model it suggests one that fits the memory you give
  it, from a dated table in `src/ract/setup/model_tiers.yaml`, and prints how to start it; it
  never downloads. For a cloud provider it names the key's environment variable and checks only
  that it is set. It writes `ract.yaml` atomically and never over an existing one
  (`--reconfigure` writes a draft and shows the diff), runs one tiny request, offers `git init`,
  and prints the next command. `--answers FILE`, `--print-defaults` and `--yolo` work without a
  terminal. Bare `ract` in a directory without `ract.yaml` offers setup, and every "configuration
  file not found" error points to it. The memory suggestion is a share of the machine's total
  memory, shown with what is free right now and a warning when that is less than the model
  needs. When setup opens the session it suggests a first request.
- Egress ledger. Every request RACT sends to another host (model providers, health checks, web
  search, MCP servers over HTTP, GitHub releases, the skill marketplace) leaves one record in
  `egress.jsonl` in the user state directory: purpose, host, status, time, bytes each way and
  the tokens the provider reported. No path, query, header or body is kept. `/cost` in the
  session and `ract doctor --egress` read it, and the `cost` field of `ract -p
  --output-format json` is filled from it. Tokens are null when the provider reported none.
  `docs/EGRESS.md` lists every outbound site.
- Ask mode. `/ask <question>` in the session, `ract run --ask` and `ract -p --ask` answer a
  question in one step, with no plan and no file written. The prompt for `ract -p` may now also
  follow the flags.
- Interactive session. `ract` with no arguments on a terminal, or `ract repl [--config PATH]`,
  opens a prompt. Plain text runs as an intent. `/plan`, `/loop`, `/set`, `/settings`,
  `/session`, `/providers`, `/config`, `/doctor`, `/report` and every other verb work as slash
  commands. Context carries between turns through a session id, history and tab completion use
  `readline` on Linux and macOS (Python on Windows has no `readline`, so on Windows the session
  has neither yet), and a failing command never ends the session. It dispatches
  through `ract.cli.main`, so tier policy and approval modes are unchanged. No new dependency.
- A step that replaces an existing file now sees that file's current contents and is told to
  return the complete updated file.
- Test fixture: a scripted OpenAI-compatible model server (`tests/fixtures/fake_model_server.py`)
  with streamed text, native tool calls, the JSON fallback envelope, reasoning output,
  truncation, stalls and server faults, plus request recording. Usable from pytest and from the
  command line for walkthroughs. Standard library only; nothing in `src/` imports it.
- `ract.tool_calls`: reads a model reply as tool calls, a final answer, or a named failure.
  It tries native `tool_calls`, then `<tool_call>` tags, Harmony channel markup, fenced JSON,
  RACT's JSON envelope, bare JSON and Python-style calls, and records which form worked.
  Unparsed tool-call markup is never accepted as an answer. Unique near-miss tool names and
  argument keys are repaired and the repair is reported; ambiguous ones are refused with a hint.
  A reply cut off at the output limit is explained with token counts. Loop guards stop a turn
  that repeats the same call three times or hits the same failure twice. Nothing in the module
  runs a tool; the read-only tools loop below uses it.
- Plan approval (ADR-0049 D12). In `default` mode, a plan of two or more steps that changes a
  file is shown once, before the first step, and you answer `approve`, `skip <n>` or `cancel`.
  Approved files are not asked about again step by step; a file the plan did not list, or a
  tool call, still asks. Skipped steps are reported as skipped by you and recorded in the run
  checkpoint. `cancel` runs nothing and the turn ends `refused`. Ctrl-C at the question cancels
  the turn. `ract -p` in `default` mode refuses such a plan before any step (exit 3) and names
  `--accept-edits`. A resumed plan is not asked about again.
- Read-only tools: `read_file`, `list_dir`, `glob` and `grep` (ADR-0047, tier 0). Paths stay
  inside the project, after links too; files RACT never sends are refused; `.git`, `.ract`,
  links and gitignored paths are skipped in walks unless asked. `grep` uses ripgrep from your
  `PATH` (never one inside the project) and falls back to a built-in search. Every result is
  labelled as untrusted file content and checked by the outbound scan before it reaches a
  model.
- An answer step may read the project with those tools before it answers: the model asks for a
  tool, RACT runs it through the tool gate and returns the result, and `tool.call.started` and
  `tool.call.finished` are in the event stream. Limits in `ract.yaml` under `agent`:
  `max_turns` (40), `max_tool_calls` (64), `max_wall_seconds` (1800); `agent.read_tools:
  false` keeps the single request. A model that repeats a call or a failure is asked for a
  summary without tools, and a reply that is a plan where an answer was asked for is asked
  again once in plain words. Tools are offered in the prompt with RACT's JSON envelope; native
  tool calling per provider is not used yet.
- File and line citations in an answer (`src/calc.py:12`) are checked against the repository.
  The end of the turn prints how many are verified, unverified or not checked and names each
  unverified one with the reason; `turn.finished` carries them as `citations`.
- UX walkthrough tooling: `tests/ux/terminal_driver.py` runs a program in a real pseudo-terminal
  (ConPTY on Windows, `pty` elsewhere) and records output with timestamps;
  `python -m tests.ux.run_baseline` runs the session journeys against the fake model server and
  saves transcripts, timings and redacted paths. Baseline transcripts and a defect list for the
  current session are in `docs/ux/baseline/`.
- `review: advisory` in ract.yaml: after each step that writes a file, the model reviews the
  change with a fresh context and reports findings with file, line and quoted evidence. RACT
  checks every finding against the repository, drops what does not check out, and shows the rest
  below the turn summary as advice; a review never changes whether a step is done. Off by
  default; `/model` shows the setting.
- `review: retry`: the defects a review finds and checks against the repository go back to
  the step once, as untrusted advice, and the step is written again through every check a step
  passes. A step retries at most twice in all (a reply cut off at the limit counts); with that
  used, the findings stay advice and the summary says so.
- `/diff` in the session shows the last turn's changes from the copies it saved, and `/undo
  list` shows each checkpoint with its time, its files and its turn.
- `ract -p --output-format json` adds an `error` object to `ract.result/1`: null on success,
  otherwise `kind` (`usage`, `config`, `provider`, `refused`, `cancelled`, `budget`,
  `stdin_stall` or `internal`), `message`, `hint` and `exit_code`. The errors found before the
  turn starts (no prompt, no config, a stalled stdin) now print a result in JSON mode too. The
  other keys and the exit codes are unchanged.
- `/review` in the session goes through the last turn's changes hunk by hunk: accept (`a`),
  reject (`r`, the turn's saved copy of that hunk comes back), edit (`e`), skip (`s`), or
  accept (`A`) or reject (`R`) the rest of the file. A file the turn created is removed when
  rejected, a file it deleted can be restored, and `/undo` still reverses the whole turn
  afterwards. The turn summary's way-back line names it.
- The egress ledger records which run, plan step and role (`manager`, `executor`, `reviewer`)
  each request belongs to, ids only; `/cost --by step` and `/cost --by role` group the model
  requests that way (`--by purpose` is the default). Older records read as before.
- Write tools and the step agent loop (ADR-0047, B-110), off until you turn them on with
  `agent.step_tools: true` in `ract.yaml`. A step that writes a file then works with
  `write_file`, `edit_file`, `delete_file`, `move_file`, `apply_patch` and `repo_map` in its own
  worktree: a change to an existing file needs the digest the model read, the step's file still
  passes every check before it is written, and other files the step changed reach yours only
  through the apply, which skips a file you changed meanwhile. A control or
  executable-configuration file (`AGENTS.md`, `.github/workflows/`, `.envrc`) is tier 2: in a
  session RACT shows the change and asks; with nobody to answer, or with `--yolo`, it is
  refused, and nothing a model writes approves it. The loop stops at `agent.max_turns`,
  `agent.max_tool_calls`, `agent.max_wall_seconds` and `agent.max_tokens_per_step`; when a call
  fails, the calls after it in the same reply do not run.
- `/checkpoint` lists the checkpoints, numbered, newest first, and `/restore N` goes back to
  checkpoint N by reversing every later turn, newest first, with the rule `/undo` uses: a file
  you changed since RACT wrote it is skipped and named, and the walk stops there. `/redo`
  brings back the last turn reversed. Every apply also keeps the snapshot it started from under
  `refs/ract/checkpoints/<checkpoint>/<n>`, so `git gc` does not remove it; the refs go when the
  checkpoint's saved copies are pruned.
- `/rewind` lists the turns that changed files by what you asked (a key in a request is
  masked), numbered; a number goes back to that turn as `/restore` does, and Enter keeps
  everything. Esc Esc at the prompt runs it where the prompt uses readline; the Windows console
  clears the line on Esc, so there it is `/rewind`.
- `--no-network` and `RACT_NO_NETWORK=1`: every request to a host that is not this machine is
  refused before it connects, named by purpose and host, recorded in the egress ledger, and the
  run exits 3. A model server on `localhost` still works. Nothing in `ract.yaml` turns it off;
  `ract doctor --egress` shows whether it is on.
- With `agent.step_tools: true` in the asking mode, a step's changes are proposed before they
  reach your files: each file is shown hunk by hunk (`diff.proposed`) and you accept, reject,
  edit or skip each one (`diff.reviewed`); only what you kept is applied, with the digest check
  (`change.applied`). A rejected hunk is never written to your files. A review that ends
  without an answer applies nothing and names the branch the proposal is on. The review
  replaces the per-step question for a step that writes a file; a tool call still asks first.
  `--yolo`, auto-accept and runs with nobody to ask apply the step as proposed.
- The tier-2 question takes `y` (once), `s` (the same files for the rest of this session) or
  no. An allowance for the session lives in memory only: `/resume` and a new process start
  without it, and the question then says "approvals from session <id> do not carry over".
- With `agent.step_tools: true`, a step that would change files in a folder that is not a git
  repository first offers, as a tier-2 action, to run `git init` and commit the current files,
  with the count and the sensitive names it leaves out (`.env` and other secret-shaped names
  are never committed). On no, or with nobody to ask, nothing is changed and RACT says how to
  enable edits later; questions about the code work without it.
- The operator key and the signed tier-3 grant (ADR-0048 D2, D3, D13). `ract policy keygen`
  makes an Ed25519 key in the user config folder, encrypted with a passphrase typed at a
  terminal (`ract-operator-key/1`: scrypt and AES-256-GCM; never from a pipe or an environment
  variable), and pins its public key. `ract policy init --guided` finds the test runner,
  proposes the narrowest rule (`[python, -m, pytest]`, network off, 15 minutes), explains each
  field, shows `.ract/policy.yaml` as a diff and signs it on one yes; `ract policy sign`,
  `status` and `revoke` do the rest. A grant holds only when your pinned key signed it for this
  folder and it has not expired or been revoked, so a cloned repository's grant grants nothing.
  The session's status line says `T3 off (no grant)`, `T3 off (grant expired <date>)` or `T3
  ask`, a notice says why a grant does not hold or that it expires within seven days, a change
  to the grant during a session suspends tier 3 until `/permissions resume`, and `/permissions`
  shows the grant. No platform confines commands yet, so every grant says `sandbox:
  best_effort` and RACT says so; the signing key stays unlocked in memory only where commands
  are confined (`unlock_window_minutes`), and `/permissions lock` closes it.
- `run_tests` (ADR-0048 D4 to D6, B-112): under a signed grant's test rule, the model can run
  the project's tests, and a request that names a failing test ends with that test run: the
  verdict says it passed or failed and the summary shows the run. Every run asks first in a
  session (`Run it once? [y/N]`), showing the full command, the resolved program, the folder,
  network and that no sandbox confines it here; `--yolo` and runs with nobody to ask never run
  one. Shells, inline code (`python -c`), `xargs`, `find -exec`, package publishing and RACT's
  own governance never run; a program planted in the project does not satisfy a rule for the
  real one. The command gets a scrubbed environment and its own home folder, stops at its time
  limit, and is recorded in the project's `commands.jsonl`: command records are in the trace;
  they are not part of the signed Rootknot. When the named test does not run, the summary's last
  line says why.

### Changed

- A signed file's record sits beside it (`src/.calc.py.rootknot.json`), and the turn
  summary names it: commit it with its file to keep the record (D-143). `turn.finished`
  and the headless result carry `provenance.sidecars`; `/undo` takes it back with its file.
- The session's screens come from MASON's views: the guided grant flow, `/permissions`,
  `/checkpoint`, the `/restore` preview (what goes back and what is left alone, shown before
  it runs), the proposed-change line, the apply result, the test-run summary, the verdict and
  the workspace lines.
- README, QUICKSTART and PHILOSOPHY no longer claim what this release does not do:
  `receipt-export` prints receipts and uploads nothing, skill templates are not signed, and no
  backend enforced the step sandbox (S-017, docs/CLAIMS_AUDIT_2.md).
- `ract run --loop --yolo` exits with the code of the cause that stopped the loop and
  prints it (`halt: T5 BUDGET_EXHAUSTED: outcome budget, exit 4`): T1 0, T2 and T4 1,
  T3, T6, T8 and T9 3, T5 4, T7 6 (D-122). It used to exit 0 for every stop but a
  regression. docs/EVENTS.md lists the table, and a test keeps it equal to the code (B-122).
- `ract handshakes approve` signs the approval with the operator key, asked at a terminal;
  an approval without that signature is listed as unsigned, unlocks nothing and still blocks
  the step's commit (ADR-0048 R2). The intent-recompile key and the per-run sandbox and ALM
  keys live outside the project now; the old places are read once more with a warning, and
  `ract policy migrate-keys` moves them (R3). See docs/UPGRADING.md.
- `ract run "<intent>"` with no terminal (a script or a CI job) no longer changes files without
  a flag: it stops with exit 3 and says to pass `--yolo`, or to use `ract -p --accept-edits`.
  Questions that write nothing still run. `ract run --loop` needs `--yolo` until the loop can
  ask. Scripts that ran `ract run` to change files add `--yolo` (docs/UPGRADING.md).
- `ract session list|export|import|backup|restore` keep their store in `.ract/sessions`, the
  folder the interactive session and `ract plan export` already use, instead of
  `.ract_sessions/`. The first time one of them runs with the default store, sessions saved in
  `.ract_sessions/` are copied in (a session already there is kept) and a notice says so; the
  old folder is left as it was and can be removed. `--store` still names any folder.

### Fixed

- `docs/EVENTS.md` documents every kind in the closed `EventKind` vocabulary
  (audit round 2, seam 1): eight kinds that had live producers but no schema
  entry (`investigator.report`, `plan.rewritten`, `plan.risk_assessed`,
  `reversal.suspicious`, `sidecar.header.legacy_fallback`,
  `trace.incremental_verify_resumed`, `trace.torn_tail_detected`,
  `trace.verify_completed`) now carry their payload schemas, and
  `tests/docs/test_every_legal_kind_is_documented.py` fails when a registered
  kind drifts out of the document again.
- `ract verify` reads the commits, not the working tree (B-236): the line-ending
  fallback runs only when the later commit is HEAD; only sidecar files count as
  RACT's own record, so any other path under `.ract/` is reported as not written
  by RACT; and away from HEAD the knot records are read from the later commit,
  with any working-tree read said plainly in the report.
- The offload store writes the stored output through `check_state_path` and a
  fresh temporary file (B-238): a hard link planted at the file name is replaced,
  not written through; the stub's first and last lines pass the outbound scan
  before they can reach a request; and a handle naming a Windows device (con,
  nul, com1) is refused on every operating system.
- Writers of the workspace and of RACT's state no longer use a predictable
  temporary file name (B-224, the class B-212 closed in the write tool):
  the per-hunk review restore, the plan approval store, the trust store, the
  signed-grant records (revoked list, entry points, guided policy, the pinned
  operator record), the setup config write, the signing sidecar header and the
  assumption snapshot all write through a fresh temporary file and one rename,
  so a link planted at a name is replaced, not written through.
- Every git command RACT runs for itself (step worktrees and commits, snapshots, reviews, the
  history and policy reads, `ract step diff`) starts with the full hardening (B-206), and the
  tool gate lists no file that no longer starts a process.
- One file lock is shared by the assumption log, the suite chain, the workspace chain, the manifest
  ledger and the run marker (B-207); each still names its own file when another process holds it.

- The setup wizard's questions and hints use plain words (B-168), and README, QUICKSTART, TIER3 and
  ARCHITECTURE no longer say false things about this build: `--loop` needs `--yolo`, `--yolo` is off by
  default, and no run writes a trace file yet (B-219, B-223).
- A path sent to a model is checked by what it resolves to (B-211): a junction or symlink
  such as `lnk -> .ract` no longer lets `lnk/sessions/x.json` reach a never-sent file.
- Two `--loop` runs that start at once no longer both write the run id (B-207): the run-marker
  lock reports a lock it cannot take instead of going on without it.
- The grant's signature and the handshake registry are written to a fresh temporary file,
  synced to disk, then renamed into place (B-207): a crash no longer leaves an empty or half
  written file, and two writers no longer share one fixed temporary name.
- A file write goes through a fresh temporary file with a random name (B-212): a hard link
  planted at the old fixed name `.NAME.ract-tmp` no longer sends the write outside the workspace.
- One address check covers every way an address reaches RACT (B-200): setup's question,
  `RACT_BASE_URL` and `OPENAI_BASE_URL`, an answers file, ract.yaml and the provider probe. An
  address with a user name, a password or a key in its query is not used, and the sentence does
  not repeat it. Error messages show an address without those parts, and every line RACT prints
  to stderr is redacted.
- A user name or password written in a provider url before the host is no longer printed in
  notices, refusals or the doctor's advice (B-199). Such a url is refused when ract.yaml is
  loaded, by a sentence that names the provider and not the url, and the probe does not contact it.
- `ract doctor --check-providers` no longer prints the start of a key that a server echoes in
  a long error body (B-198): the body is masked whole, then cut. Every cut of a server reply or
  of an error's text is masked the same way, and a test keeps it so.
- In a headless run, an approval nobody can answer (a tier-2 change, a tier-3 command or fetch)
  is now emitted as `approval.requested` and `approval.resolved` (`by: unattended`) and listed
  in the result's `denials` (B-193). `--fail-on-denial` stops the run at the first one and
  exits 3; it was parsed and never read.
- A refused turn reports the outcome `refused` with exit 3, as the loop does (B-196); the turn
  said `failed`. A trusted headless run lists the extensions it loads in `session.started`, and
  the documented extension kinds now include `command` and `network`.
- A step whose provider could not be reached is shown as failed, as the turn is, and no longer
  as refused (B-196): a step is refused only when the turn exits 3 for its error.
- `ract setup --reconfigure` and `--add-provider` show a diff that masks a literal key already in
  ract.yaml and keeps `${VAR}` references (B-202). MCP connection errors, a server's own error
  output and `ract mcp call` results are redacted before they are shown.
- A broken `ract.yaml` is reported by line and column only (B-202): the YAML error text quoted
  the broken line, so a key written on it was printed by `ract doctor`, `ract run`, a session,
  headless runs, the preflight check and setup's answers file.
- An unset key variable (`api_key: ${VAR}`) and the other configuration problems now exit 2
  with `error.kind: config` in a session, `ract -p` and `ract run` (B-194); they exited 1 with
  `internal`. The providers and the exit table share one list of these sentences, and `ract run`
  uses the same exit table as the other runs.
- An approval screen shows the change, command or path it asks about as written (B-184):
  indentation and double spaces are kept, a tab is shown as `\t`, and a line breaks only where
  it passes the width. A combining mark no longer starts a continuation line. Every approval
  screen escapes control, format and direction characters the same way (B-204); four screens
  printed U+061C and the zero-width characters raw.
- An allowlisted command asks when a runner configuration or test file it would load changed,
  whatever the case of the file's name (B-215): `PYTEST.INI`, `Pyproject.toml` and
  `sub/Conftest.py` were not recognized, though Windows and macOS open them by any case.
- RACT no longer writes its state through a link or junction under `.ract` (B-213): the memory
  arena, plans, sessions, run checkpoints, undo copies and pending patches refuse with a plain
  sentence when `.ract` or a folder in it is a link. A cloned repository could point
  `.ract/memory` outside the project, and the arena was written there.
- A message with brackets in it is shown as written (B-185): `[line 3, column 2]` or a path like
  `C:/proj/[draft]/ract.yaml` was deleted from the line, and `[/bold]` stopped the turn with an
  error. The plan lines of `ract run` show the model's brackets as text too.
- One list decides which file names hold secrets (B-205): the model's reads, writes, the step
  snapshots, git staging and the threat model agree on it. Every OpenSSH private key name, key
  stores (`.p12`, `.pfx`, `.jks`, `.keystore`, `.ppk`, `.kdbx`) and token files (`.netrc`,
  `.pypirc`, `.git-credentials`) are secret; an env file whose last suffix is example, sample,
  template or dist as written is a placeholder (`.env.local.example`; `.ENV.EXAMPLE` stays secret).
  `id_ecdsa` and `id_dsa` were shown to the model.
- RACT no longer runs a bare `git worktree prune` (B-230): it drops only its own step worktree
  registrations whose folder is gone, and never one that the other system (Windows or WSL) made
  in a repository used from both.
- RACT's own git reads in the historian, the fences, the step commits, the worktrees and the
  setup check start git with the full hardening (B-206), so a repository's fsmonitor or hooks
  no longer run a program for them.
- RACT starts git by its full path, and on Windows no program it starts is taken from the
  current folder (B-214): a `git.exe` a repository put at its top could run in place of git. A
  program name with a dot in it, such as `python3.11`, is now found on PATH on Windows.
- The `--loop` test run no longer inherits provider keys, and `ract run` and the loop redact what
  they print and store (B-201): streamed text and step results on the screen, the test output in
  the loop report, the session files and the error memory. A key the run knows is shown as
  `[redacted]`.
- Each mode word has one meaning in a session (B-191): `/mode` sets how file changes are handled
  and its text starts with "File changes:"; `/permissions ask|allowlist` sets how tier-3
  commands are handled and says "Tier-3 commands:". `/set auto` is retired, because `/set auto
  on` selected the mode that asks; it now names `/mode default` and `/mode auto-accept`.
  `/set mode` is now `/set task`, and the old name still works for now.
- The tier-2 git questions (commit, branch, worktree) and the sandbox section of `ract doctor`
  now show the screens designed and walked for them (B-225); the exact git command stays on the
  question. A machine whose sandbox does not run commands reads "best effort, not enforced on
  this machine".
- The session's event stream tells the truth in more places (B-195): an interrupted turn says
  what changed is not known (it said the folder was not a git repository), `mode.changed` carries
  the real tier-3 state, a turn started from the queue says `queued`, the events follow the
  session after `/session` and `/resume`, and `session.resumed` and `session.rewound` are emitted.
- An edited plan is announced again with its assumption, confidence and the planned flag
  (B-195): the summary lost the plan's assumption line after an edit.
- The WSL mutation runner reads the distribution list right (it took the list's header for a
  distribution), passes `RACT_MUTATION_TARGETS` and `RACT_TEST_RUNNER` through `WSLENV`, and
  refuses a network path with a sentence (B-231). With no running distribution it says so and
  runs nothing.
- Program text and help say what is true (B-220): a run's provenance warning and `ract
  provenance verify` no longer say runs do not sign; the `--bare` help says it holds for trusted
  repositories too; `ract trace` takes a run id, a run folder or an events file; the `whisper`
  and `refactor` examples run; `ract memory <sub> --help` shows the sub-verb's help; the global
  `-p`, `--no-color`, `--plain` and `--no-network` are in `ract --help`; `ract -p --help` lists the
  stdin rule and every exit code; `ract setup --help` lists its exits.
- Doctor advice, the model list and the no-config notice wrap by terminal columns (B-210), so wide
  characters no longer push a line past the edge.
- In a session's auto-accept mode a tier-2 call (a commit, a branch, a control file) asks
  at the terminal, as a tier-3 command does; auto-accept covers file edits only (D-145).
  Headless runs and `--yolo` still refuse tier 2 and tier 3.
- `git_commit` scans the commit message for secrets as it scans the staged files, and refuses
  before the question when it finds one (D-145).
- The tier-3 entry-point record is bounded at run entry (B-148): at most 5000 entry points,
  64 MiB and 10 s. Past a bound the record is unknown, so every tier-3 command asks, and the
  turn says which bound was hit. A very large repository no longer makes this read slow or
  large in memory.
- A step worktree an ended RACT process left in `.git/ract-worktrees` is removed when the
  next session starts, and the session says so (B-146); only worktrees RACT made and no
  running process owns are touched. `/exit` after an interrupt waits up to 10 s for the
  step's cleanup and, past that, names the worktree and the `git worktree remove` command.
- On Linux, Ctrl-C mid-stream then `/exit` no longer leaves a step worktree listed (G-249):
  the cancel ends the stalled model read at once, a worktree whose git was cut short is
  pruned, and the session removes its own step worktrees when it ends. Esc Esc reaches
  `/rewind` at once on a POSIX terminal whose system inputrc binds Esc Esc sequences.
- Every line `ract setup` prints wraps to the terminal width (40 to 80 columns), with a
  hanging indent (B-163); at 60 columns five of them ran to 64 to 124 characters. A diff
  is printed as it is.
- Setup's questions and the note that a key was withheld wrap to the terminal width too
  (B-164); at 60 columns they ran to 64, 87 and 227 characters.
- A model server that echoes the key in its error body (for example a 401 that repeats the
  Authorization header) no longer gets the key printed (B-165): the provider redacts the
  body whole before it shortens it, in every error text it makes, and setup redacts what
  it prints. `ract.yaml` never held the key.
- In the hunk review of a proposed change, `s` (skip) applied the hunk; it now makes no
  change to what is on disk on every review screen (B-183): a proposed hunk is not applied
  (`s skip (do not apply it)`), and in the post-turn `/review` the hunk stays as the turn left
  it (`s skip (leave it as it is)`). Only `a`, `y` and `yes` accept a hunk. The whole-file
  questions say when an answer is not understood and show the choices again.
- A turn whose tests passed and that then changed a file again now reports `stale`, not
  `verified` (B-192): the turn counts every write that changes a file's content, the step
  tools' writes included, and each test run keeps how many came before it. A test run that
  collects no tests reports `no-tests`. The headless `ract.result/1` carries the same status.
- `RACT_PRESET_BASE_URL=preset=url` points a preset at another address in what `ract setup`
  writes, for tests and walks against a fake server (B-160d). It is a security-class
  variable that `ract doctor --env` shows, and it never pairs a key with a host: only
  `RACT_KEY_HOSTS` does, so a key is withheld from an overridden address. A malformed value
  (not `preset=url`, an unknown preset, credentials) refuses setup and sends nothing (G-265).
- `ract setup --add-provider` adds a second endpoint to an existing `ract.yaml` (B-160c):
  the same questions, a diff before writing, the same health check on the new provider;
  the manager provider stays, a provider of the same name gets a numbered name, and the
  new block is added as text, so every other line of the file, comments included, is kept.
- `ract setup`'s provider list says `(no key needed)` for the presets that read no key
  (llamacpp, lmstudio, ollama, vllm), where it printed `(key in )`, and picking one no
  longer prints an empty variable name (B-160e).
- After a preset is picked, `ract setup` prints the address it uses and the variable it
  reads, one line each (B-160b); the key's value is never shown.
- When no model server answers on the default ports, `ract setup` asks once for your
  server's address (B-160a). A typed address that answers is written to `ract.yaml`; one
  that does not is named (`nothing answered at <address>`) and not written; one holding a
  user name or password is refused before any request, and not echoed. Looking again
  and still finding nothing now writes no config, where it wrote Ollama's default address
  and its check failed; typing `skip` is the explicit way to write that default.
- The git tools are harder to walk around (G-239). The commit's secret scan reads every
  staged file whole from the index, so a line starting with `++`, a binary or `-diff` file,
  a large file or a U+2028 separator no longer hides a key; it also finds `sk-ant-` keys and
  bare 40-character AWS secrets, and a scan that cannot run refuses the commit. `git_add`
  and `git_commit` refuse `.env`, `*.pem`, `*.key` and `id_*` key files by name. A project
  that is not its own repository's top folder, a repository whose config defines a filter
  program or whose attributes name an undefined filter, a link on the worktree path, and a
  push from a repository whose own config sets a transport, proxy, credential helper or
  other URL are refused. Signing is off for every git call. The tier-2 question quotes the
  command and, for a commit, lists the staged files with their line counts and the scan's
  result; the commit runs only if the staged change is still the one shown. The push
  question shows the resolved push URL and commit, and its handshake id is
  `git-push:<URL>:<branch>:<commit>`, so one approval covers one URL and one commit.
- `web_fetch` asks before every fetch in every mode (D-144; "for this session" covers that
  exact URL), and resolves a host only after the string check, the secret scan of the URL
  and the answer, then connects to that vetted address with the host name kept for TLS
  (G-238). The body is read raw with no content coding up to the cap, one 60 s deadline
  covers DNS, redirects and the body, a control character in the URL is refused, the grant
  pin is read again after the question and before each hop, NAT64, 6to4 and mapped IPv6
  forms of inner addresses are refused, and a connection error is a plain refusal.
- A malformed tool call is answered plainly and never reaches a tool (B-140): a call to a
  tool the loop does not offer gets the offered names back, arguments that do not fit get
  what was wrong and the fields the tool takes, and arguments encoded twice as a JSON
  string are decoded once more. Three malformed calls in one step end it with "The model
  did not produce a valid tool call", and the turn says so.
- A model that answers a request with tool calls (or in prose twice) instead of a JSON plan
  no longer ends the turn with "Could not parse JSON plan" (B-137). The request becomes one
  step through the step agent loop, its first reply's tool calls the step's first turn,
  each call through the same tier gate and approvals as any other. The plan is shown for
  approval in default mode; headless without `--accept-edits` refuses it and says so.
  `plan.proposed` and the headless JSON result carry `planned: false`. A model that
  answers in prose twice gets the same one step when `agent.step_tools` is on; with it off,
  that still ends with the plain sentence (B-086), and tool calls are refused, named.
- A path such as `C:\Windows\x.py` is refused on Linux and macOS as on Windows (B-136):
  it was read as a relative name inside the project.
- `ract memory init` checks the language servers side by side under one 20 s budget (B-136,
  B-134); a server that does not answer is named and the index goes on without it.
- A memory folder that is a link out of the project is not read, and the turn says so on
  stderr and in its notes (B-135).
- A test file a turn creates or rewrites that imports nothing of the project and starts no
  process (a test that defines the value it checks) is named next to the verified line: "tests/
  test_notes.py does not use project code". It is a warning; nothing is refused, and it never
  makes a turn verified. `turn.finished` carries `verification.no_project_code`.
- A request that names a test or says one fails (`tests/test_calc.py::test_add fails, fix
  it`) no longer ends on a plain "Done" while RACT runs no tests: the summary says `verified:
  no` and its last line is "not verified: RACT cannot run tests yet (slice c)". The
  `verification` object of `turn.finished` carries `test_named`.
- A Python file a step writes is refused when it imports a project module that does not exist
  (`from src.notes import NOTEX` with no `src/notes.py`): "it imports src.notes, which does not
  exist (line 1)", and nothing is written. A module counts as the project's when its first part
  is a package or folder of the project (in the root or in `src/`), or the import is relative.
  A file another step of the same plan writes counts as existing. The standard library and
  installed packages are still not checked.
- At 60 and 40 columns the session's status line folds between its items, so `T3 off` stays
  on one line, and `/review` lists its choices folded at the commas and asks `answer:`, so no
  choice is split.
- A web-search key and a GitHub release token are masked wherever RACT shows text, like a
  provider key. `/help` no longer splits a word at 40 columns: `/cost [--by KEY]`, `/mode [MODE]`
  and `/doctor [OPTIONS]` name their options in the description.
- A provider key is masked wherever RACT shows text, also when it has no recognizable shape:
  when the key is resolved, its exact value and its URL-encoded and base64 forms are kept in
  memory and replaced with `[redacted]` in events, errors and streamed text (for example a
  gateway that echoes the rejected key in its error). The key is never written to disk.
- On Windows, a Ctrl-C pressed just as a question or the prompt appears interrupts at once; it
  was held until the next Enter when it landed before the console read started.
- A step no longer writes through a hard link (a file with a second name, which may be
  outside the project): the write is refused and names the file. On Windows, the device names
  `COM0`, `LPT0`, `CONIN$`, `CONOUT$`, `CLOCK$` and the superscript forms of `COM` and `LPT` are
  refused like `CON`, and a name such as `a~1.txt` is an ordinary file unless it is the short
  name of another file.
- `ract --version` and `ract --help` start about 0.15 to 0.2 seconds sooner again: the HTTP
  library loads when the first request is made, not at every start.
- `ract` starts about 0.2 seconds sooner (`ract --version` included): the provider checks,
  the structured-output schema and the loop controller load when a command first needs them.
- Clearer messages: a mistyped option prints one line and `Try: ract --help` instead of the
  usage block; a missing `ract.yaml` names `ract setup`; `ract fence inspect` says when the file
  does not exist; `ract doctor` says in plain words that files are not signed yet; a used-up
  novelty budget names `--allow-novelty-overrun`; `ract memory init` no longer prints an
  internal LSP line.
- The step lines and the unsigned-files list name a file as the disk spells it (`Readme.md`
  when the plan said `README.md` on Windows), as the changed-files line already did.
- When the model answers a request in prose instead of a plan, or with a plan that has no
  steps, RACT asks once more and shows the plan's shape; if the second answer has no steps
  either, it says so in one sentence and suggests a larger model or `/model`.
- A Python file a step writes is checked for names it imports from the project that do not
  exist there (`from src import NOTE` when `NOTE` is in `src/notes.py`); such a write is
  refused with the line and the name, and nothing is written. Only source is read.
- A cancelled plan in `ract run` is the choice you made: it prints as a plain line and the run
  exits 0, without the provider-check hint.
- In a terminal, `ract run "<intent>"` and `ract "<intent>"` with no approval flag now ask
  before they change files, as the session already did: the plan question for a plan that
  changes files, then each step outside the approved plan. Before, they wrote without asking.
  `--yolo` skips the questions; `ract -p` still refuses changes without `--accept-edits`.
- `ract -p` with a stdin that a parent leaves open no longer waits without a word: after five
  seconds of nothing a notice goes to stderr, and after 30 seconds (`RACT_STDIN_IDLE_TIMEOUT`)
  the run exits 2 with a hint. `--no-stdin` skips reading stdin. Data that keeps arriving is
  read to the end.
- A step that rewrites a file which starts with a byte order mark keeps the mark; a file
  without one, and a new file, get none, even when the model's reply carries one. A change
  sent as a diff keeps it too.
- "Approval denied for step N" names the step you were asked about, and its hint says the step
  was not approved. A resumed run says a step "was refused" or "failed" instead of "was
  interrupted" when that is how it ended.
- The `--- path ---` label RACT puts around a file in the prompt is no longer written into the
  file when the model copies it into its reply; a reply labelled as another file is refused.
- A file step whose reply was cut off at the model's output limit, or a Python file that ends
  inside a string, is asked for once more and refused if it is cut off again; nothing is written.
  A new Python file that does not parse is refused with the line of the error, as a replacement
  already was. Before, both were written and reported done.
- `plan.proposed` and `plan.approval_requested` carried a plan step's text as the model wrote
  it, terminal escapes included; that text is now made printable, as every other event's is.
  `plan_hash` is unchanged.
- `api_key: ${VAR}` with VAR unset now stops before any request and names VAR, with what to do.
  Before, the request went out without the key and the turn failed with no cause.
- A repository can ship a `.rack` that is a file or a link. The first-run move of `.rack/` to
  `.ract/` now leaves such a `.rack` as it is and says so; before, a file named `.rack` became a
  file named `.ract`. Undo, rollback and session import refuse a saved path that holds a NUL
  character (it crashed the write), and on Windows a name with a `:` stream suffix or a device
  name such as `con` or `aux.txt`.
- A `.ract/handshakes.json` shipped in a repository could mark a handshake as approved,
  and that widened the run's capability manifest. An approval now widens only when this
  machine recorded it (`ract handshakes approve` writes a mark in the user state directory
  holding the approved item's digest). Approvals made before this change must be given
  again (docs/UPGRADING.md) (S-035).
- Other files a repository can ship (`.ract/refactor_ledger.json`, the memory arena,
  `.ract/error_memory.jsonl`, the env allowlist, the assumptions log) and `session.json`
  are read with a size cap and without following a link, and a wrong shape is refused or
  ignored instead of raising an error the reader did not document. The refactor ledger no
  longer reads `allow_debt_override` or a looser threshold from the file (S-035).
- Files a cloned repository can ship no longer steer writes outside the workspace. Session
  rollback snapshots (`.ract/snapshots/`), consolidation proposals in `.ract/handshakes.json`,
  consolidation backups and imported session exports each turned a value from the file into a
  path with no check, so `--rollback`, `ract consolidate apply` or `rollback`, and `ract session
  import` could write next to the repository. Every such path must now stay inside the
  workspace, and session and proposal ids are plain names. Present in v0.5.2.
- `ract report --last` (and `/report`) printed "Assumption: no plan" and "Confidence: 0.0" for a
  turn whose plan had both: the session record dropped the plan of every run that executed. It
  now keeps it, and a turn without a plan says "not recorded" instead of showing a default.
- A model reply with CRLF line endings no longer shows a replacement character before every line
  break in the session. Carriage returns are dropped from displayed text; the file on disk is
  unchanged.
- A model server that is not running is reported in about 1.5 s instead of 15 to 25 s, as
  "nothing is answering at <url> (connection refused)" with the hint to start it. A connection
  nothing answered gets one quick retry; read timeouts keep the full backoff. Retry lines and
  errors no longer print raw operating-system error text such as `[WinError 10061]`. On Windows a
  refused local connection takes about 2 s to report (4 s for `localhost`), so the connect
  timeout for a server on this machine is 0.5 s.
- MCP tool calls (over HTTP and to stdio servers), GitHub release names and notes were sent
  without the secret scan that provider requests get; they are scanned now. A text release asset
  that holds a secret-shaped value is refused instead of uploaded.
- A step's reply no longer replaces a file with something that is plainly not that file. A step
  whose action asks for information (read, show, explain, list, find, review, check, summarize,
  describe, with no write verb such as fix or update) and names an existing file is run as an
  answer step: its reply is shown as the answer, a note says the file is not written. Before any
  other write to an existing file, a Python, JSON, YAML, TOML or INI file that parsed must still
  parse, and any other file over 50 lines is not cut to under a tenth of its size unless the step
  says it deletes or truncates. A refused step writes nothing and the hint names `/ask`. Every
  file a turn replaces or deletes keeps its previous bytes in the user state directory, outside
  the repository, and the turn summary says `/undo` restores them; the newest 20 turns are
  kept. With a model
  that followed the v0.5.2 prompt, asking about a file could replace it with the answer.
- A step refused by RACT itself was reported with the hint "start your model server"; the hint
  now matches only a refused connection.
- A question no longer writes a file. A plan step with no target file became `output.txt` (or
  `test_results.txt` when the action mentioned tests), so asking RACT where something is wrote
  the answer into the repository, and a step meant only to read a file overwrote it with its
  reply. A step with no target file is now an answer step: its reply is the answer, nothing is
  written, and it runs without a worktree or step branch. The manager prompt says a step names a
  file only when it writes it. A turn of answer steps skips the coverage and mutation gates,
  which run the project's tests. A project with its own `prompts/manager.txt` keeps using it;
  remove that file to use the new bundled prompt.
- Every run keeps worktree isolation, including the second run and multi-step plans. A run's
  first step now starts from a snapshot of your working tree (uncommitted and untracked files
  included; `.ract/`, secret-shaped files and files over 2 MiB left out and never changed by the
  run, with a note naming the large ones), built in a temporary index so your
  index, branch and stash are untouched. Before, a run after any edit found the tree dirty and
  silently wrote in place with no isolation, and a step could not change a file an earlier step
  had created. Applying a step is now content-based and never touches the index; untracked
  files of yours are never changed; per-file errors are reported with what was already applied;
  the saved patch is byte-exact and the hint names the step branch. When a run does write in
  place (not a git repository, or `substrate_loop: false`), it says so.
- `.ract/` no longer shows as untracked in `git status`: a run adds it once to the clone-local
  `.git/info/exclude` (your `.gitignore` is not touched). `ract doctor` lists RACT's
  `rootact/step/*` branches with the oldest one's age, and `ract doctor --prune-step-branches
  [DAYS]` deletes those older than DAYS (default 14). Nothing is pruned unless you ask.
- Runs no longer print "sandbox_env: scrubbed N environment variable(s) ..." to the terminal.
  The summary is logged at INFO and still recorded in the `sandbox.env_scrubbed` event.
- Seven event kinds that RACT emitted (`tool.invocation.pre`, `post`, `refused`;
  `compensator.installed`, `discarded`, `applied`, `refused`) were missing from the closed
  `EventKind` vocabulary, so a live trace writer dropped them. They are registered
  (`docs/EVENTS.md` schema_version 11), and a test now fails when source code emits an
  unregistered kind.
- Hook commands (`.ract/hooks/*.json`) no longer receive your API keys and tokens. They ran with
  a copy of the whole environment; they now get the sandbox default allowlist minus
  credential-shaped and library-injection names and RACT's own variables, plus the
  `RACT_<CONTEXT>` values. A repository's `.ract/sandbox_env.allowlist` does not widen it.
- `ract doctor` reports sandboxing as it is in this build: per platform, whether a backend binary
  is on PATH, that no backend runs commands yet, and filesystem, network and process limits as
  not enforced (`--json` carries the same under `sandbox`). The Linux and macOS backends render
  a bubblewrap command or Seatbelt profile and never execute it. `docs/THREAT_MODEL.md` and the
  README now say the sandbox described there is the design, and that `--allow-unenforced-sandbox`
  does not exist yet.
- Provenance is reported honestly. `ract` runs have not been signing the files they write: the
  executor's Rootknot dependencies (`install_v4_provenance_deps`) have no production caller, so
  no sidecar or index row was written, silently. A run that writes files now names the files it
  wrote without a Rootknot, `ract doctor` states that runs do not sign in this release, and the
  README, `docs/PROVENANCE.md` and `docs/PHILOSOPHY.md` describe the current state. Wiring the
  signing path waits on the operator decisions in ADR-0048 (R3, R4). `ract provenance verify`
  reports a file with no recorded Rootknot as `unsigned` and says this is not evidence of
  tampering; `invalid` is kept for a Rootknot that fails to verify. `docs/index.md` and
  `docs/SIGNATURE.md` carry the same current-state note.
- `ract doctor` without `--check-providers` contacts no provider, as before, and now says so: the
  title reads "config checks passed" and a closing line names `ract doctor --check-providers`.
  `--json` output gains `providers_contacted`. The `--init-provider` hint now suggests that
  check before the first intent. A config pointing at a server that was not running used to
  report every check as passed.
- A run no longer commits onto your branch. The worktree-per-step path committed each step and
  moved the checked-out branch with `git reset --soft`, leaving an unrequested `rootact step`
  commit, an unchanged working file and a staged reversal; a read-only question or a denied
  approval also left a commit. Each step's commit now stays on its `rootact/step/*` branch and
  its changes appear in the working tree as unstaged edits. RACT's `.ract/` state is never
  copied. Nothing in your working tree is overwritten or deleted: a path is applied only when
  it is absent (for a new file) or a tracked file still identical to the step's starting point.
  Anything else, including an untracked or ignored file, a directory or a link at the path, or a
  file you edited or deleted during the step, is left alone and the step's patch is saved under
  `.ract/pending/`. This is a stopgap; ADR-0047 D6 (review before apply) replaces it.
- Interactive session: after a turn that failed once the session had been saved, every later
  intent failed with "Session ... already exists" until `/session new`. The session now resumes
  whenever its file exists on disk.
- Paths from model output are resolved inside the project or refused. `DiffApplier` took target
  paths from diff headers and accepted `../` and absolute paths; `Executor._write_artifact`
  refused absolute paths silently but wrote `..` paths. Both now use
  `ract.workspace_path.resolve_workspace_path`, which refuses `..`, absolute paths outside the
  project, writes through symlinks or junctions, writes under `.git` or `.ract`, `/proc/*/root`,
  and on Windows UNC and device paths, drive-relative paths, reserved device names, alternate
  data streams, trailing dots or spaces and 8.3 short names. A refused write fails the step with
  a hint instead of being skipped.
- `mypy src --platform linux` failed on `Executor._target_file_block`, which received
  `str | None` for a `str` parameter. The parameter now accepts `None`, which the function
  already handled. Nine files from this release were not `ruff format` clean; they are now.
  `scripts/ci_parity.py` runs the CI lint, format and type-check commands locally, plus mypy for
  Linux and macOS when run on another platform.

- `scripts/install.sh`: `--venv` takes an optional directory (default `.venv`) and no longer
  swallows the next option; the script is executable; the clone directory no longer has to be
  named `RACT`; a failed pip install outside a venv suggests `--venv` (PEP 668).
- Manager provider resolution: an unset `manager_provider` no longer produces "Provider slot
  'local' is not configured". RACT uses a provider named `local` or the only provider, and
  otherwise says what to set. `ract config validate` and `ract doctor` report keys indented
  under `project:`, the unread `prompt_file:` key, `type:` for `adapter:`, and
  `max_output_tokens:` for `max_tokens:`.
- `max_tokens` in a provider slot is honored. `local_http` sends no output limit by default
  and its default timeout is 600 s (was 60 s). An invalid value is reported as a slot error.
- Reasoning models: `<think>` blocks are stripped from plans and step output, and a truncated
  or reasoning-only response is reported as such (`finish_reason=length`) instead of as a JSON
  parse error.
- The executor refuses to write an empty answer to `expected_artifact`, so a failed step no
  longer truncates an existing file to zero bytes.
- Step context no longer includes `ract.yaml`, `manager.txt`, the prompts directory or
  `.ract/`, which caused models to answer steps with the planner prompt's JSON format.
- Capability tier 3 matches whole words, so "execute the tests" and the file name `src/ssh.py`
  are no longer refused. `run the shell command`, `exec(`, `curl`, `ssh` and `publish` still are.

## [0.5.2] - 2026-08-22 â€” Deep-Audit Hardening

Six-module hardening release layered on the v0.5.1 spec-completeness
tag. Fifteen deep-audit findings from the paired Ox-Alpha-partnered
Deep Audits A (Rootknot v4 + substrate) and B (runtime + trace +
memory) closed as primary work; roughly twenty smaller carryover
items either folded into module_06 (six) or routed to
`docs/RACT_v0.6_BACKLOG.md` (fourteen+). See
`docs/UPGRADING.md` for the v0.5.1 â†’ v0.5.2 operator path and
`docs/RACT_v0.5.2_HARDENING_SPEC.md` for the master module map.

Every module executed the 13-step build discipline authored 2026-
08-22 per operator directive (spec + PRE depth/lateral chain +
intent grounding + architecture grounding + Ox-Alpha co-build +
build + POST depth/lateral chain + audit SP + POST-post
chains + BUILD-what-emerged + UX grounding). Every module carries
a fragment under `_BUILD/ract_v0.5.2_hardening/module_0N.md`
(gitignored; operators with local pipelines have them).

### Findings closed

- **module_01** (Rootknot v4 signature hardening) â€” `55df494` +
  amendment `f79805a`. Closes DA-A F-1 (v4 fields absent under
  v4-labelled construction), F-2 (canonical bytes emit v4 fields
  only when truthy), F-5 (sidecar reader silently defaults
  ``run_id`` to empty), Ox-M-1 (verifier had no
  ``min_acceptable_schema_version`` policy â€” DOWNGRADE attack),
  Ox-M-2 (``schema_version < 3`` accepted unknown v9 with drifted
  semantics â€” forward-compat drift). Ships
  ``Rootknot.__post_init__`` v4 gate, authoritative verifier-side
  ``_check_rk3`` cross-check, ``--min-schema=N`` CLI flag, and a
  closed known-versions allowlist ``{1, 2, 3, 4}``.
- **module_02** (Sandbox env library-injection defense) â€”
  `0829758` + `c447aec`. Closes DA-A F-3 (NEVER_PASSTHROUGH
  missed classic library-injection vectors), Ox-M-4 (Windows
  allowlist-key case sensitivity gap); routes Ox-M-3
  (repo-committed allowlist trust-tier redesign) to v0.6 with a
  reserved ADR-0048 slot. Extends NEVER_PASSTHROUGH by 40+ env
  vars (``LD_PRELOAD``, ``LD_LIBRARY_PATH``, ``LD_AUDIT``,
  ``DYLD_INSERT_LIBRARIES``, ``PYTHONPATH``, ``NODE_OPTIONS``,
  ``BASH_ENV``, ``GLIBC_TUNABLES`` [CVE-2023-4911],
  ``GIT_SSH_COMMAND``, ``SSL_CERT_FILE``, ``HTTPS_PROXY``,
  ``CARGO_HOME``, ``RUSTFLAGS``, ``PSMODULEPATH``, more).
- **module_03** (Subagent lifecycle + PID-reuse hardening) â€”
  `53338df` + `06b6f04`. Closes DA-A F-4 (poll-exited short-
  circuit skipped tree-kill; grandchildren leaked) + Ox-M-5 (no
  PID identity check â€” reused pid could receive a delayed kill
  intended for the original tenant). Ships spawn-time
  ``creation_time_ns`` capture, ``process_identity.same_process``
  tri-state check (SAME / REUSED / DEAD), unconditional
  ``tree_kill_invoked`` emit on every ``dispose``, and a new
  ``pid_reuse_detected`` event kind for auditors.
- **module_04** (Run_id continuity â€” sidecar schema + subprocess
  plumbing) â€” `eefbad0` + `ec33975`. Closes DA-B F-3.1
  (subprocess subagent had no way to inherit ambient run_id) +
  F-3.2 (sidecar payloads carried no schema binding). Ships
  ``ract.sidecar_header.write_sidecar_header`` primitive
  (envelope + tmp+rename atomicity, header carries
  ``sidecar_type`` + ``schema_version`` + ``run_id``),
  ``RACT_RUN_ID`` env plumbing via
  ``_capture_ambient_run_id_once`` + ``_inject_ract_run_id_env``
  (single ambient snapshot per spawn defeats concurrent-binder
  races; RACT_* keys stripped from parent env before re-inject),
  and ``bootstrap_ambient_from_env`` at subagent boot with
  synthetic-orphan fall-through.
- **module_05** (Trace log durability + honest verify) â€”
  `b80b3cb` + `c224db5`. Closes DA-B F-4.1 (O(NÂ²) full-file
  reseed on every verify), F-4.2 (``iter_events`` materialised
  the whole file), F-4.4 (strict UTF-8 decode of torn tail
  aborted verify), F-4.5 (``raw.split("\n")`` mishandled CRLF),
  F-4.6 (verify result shape inconsistent â€” some paths bool,
  some dataclass, some raise). Ships per-run
  ``{run_id}.verify.json`` incremental warm-verify sidecar,
  streaming ``iter_events`` generator, torn-tail UTF-8 replace
  (last line only; body stays strict), universal newline reader
  (binary mode + ``splitlines``), and the ONE
  ``TraceVerifyResult`` frozen dataclass with closed
  ``Literal["VALID","INVALID","TORN_TAIL","TAMPERED"]`` status
  every verify entry point returns. New CLI verb
  ``ract trace verify`` â€” warm by default, ``--cold`` for
  full-file replay, ``--json`` for machine-readable output.
- **module_06** (Memory system polish + docs + release close) â€”
  this commit series. Closes DA-B F-5.1 (dataclass grouping
  regex docstring dishonestly claimed foreign aliases would not
  match) + F-5.4 (watcher ``on_moved`` src-delete + dest-create
  reorder race on network shares); adds ``ract memory
  verify-consistency`` cross-index consistency verifier
  (``IndexConsistencyReport`` dataclass mirroring the
  ``TraceVerifyResult`` shape per Ox-Alpha co-build Q4 hybrid
  verdict); folds three MUST-FOLD carryover items (module_01 Q3
  unknown-sidecar-schema refusal; module_04 C-6 ``RACT_RUN_ID``
  boundary regex validation; docstring-honest per Ox-Alpha co-
  build Q7 verdict); defers three SAFE-TO-DEFER carryover items
  to v0.6 (module_04 C-4 ``--strict-sidecar-headers`` opt-in;
  module_04 C-8 ContextVar reset fixture; module_05 C-14
  ``memory_budget_bytes`` kwarg). See `docs/RACT_v0.6_BACKLOG.md`
  for the full deferred inventory.

### Golden hash re-lock

Per Ox-Alpha co-build Q2 verdict, the re-pin is NARRATED (not
silent). ``tests/test_source_digest.py::test_golden_hash_matches_locked``
was RED at HEAD across modules 01-05 because the shipped source
tree changed. Old value:
``7d6c8b1c56449bb96428e6ba75af2b24b85adadb66e75ca6b2c7a0ad7afc41fb``.
Value at v0.5.2 tag close:
``e8be3860fc36ca4ea3c646c4e5f1d2c12f74d7050df36b478771fafdcbc99306``
(``src/ract/source_digest.py::GOLDEN_HASH_CONSTANT``; the intermediate
``0f00...f2ba`` locked at module_06 primary was superseded by the
SP-amendment source touches). Post-tag CI-fix closure (Ox Alpha Q1
mypy sweep + type-drift closure + EVENTS.md schema bump to "10")
re-locked to
``52bed4baf4aab67f67b9e52c09123dfe0f6679a95de8365a543ec8d5df8d239a``.
The tag remains v0.5.2 â€” the source-tree churn is post-release
CI-fix follow-up (the tag object still resolves to the pre-fix
tree); the constant tracks the post-fix tree so
``test_golden_hash_matches_locked`` stays green on ``main``.
Rationale: every code fold above is spec-authorized; the re-pin
is the mechanism working as designed. Operators who audit
external RACT builds should compare against the new constant.

Diffstat summary (Ox Alpha SP Q3 fold: tamper-evidence beyond
the narration): `git diff --stat 300f8b22..v0.5.2 -- src/`
reports **26 files changed, 6293 insertions(+), 152 deletions(-)**
concentrated in the six hardening-module surfaces named above.
An auditor recomputing the golden hash at the tagged commit
should observe the new constant match; a mismatch against a
different constant with the same tag SHA indicates a
build-tree-tamper vector and MUST NOT be accepted as authorized.

### New CLI verbs / flags

- ``ract trace verify <run_id>`` â€” warm/cold trace-log chain
  verify. Exit codes 0/1/2/3 (VALID or TORN_TAIL / INVALID /
  TAMPERED / no log).
- ``ract memory verify-consistency [repo_path]`` â€” cross-index
  consistency. Exit codes 0/1/2 (CONSISTENT / INCONSISTENT /
  UNAVAILABLE).
- ``ract provenance verify --min-schema=N`` â€” reject any sidecar
  below schema version N.

### New event kinds (all additive)

- ``substrate.subagent.tree_kill_invoked``
- ``substrate.subagent.pid_reuse_detected``
- ``substrate.subagent.orphan_reaped``
- ``runtime.run_id.env_injected``
- ``runtime.run_id.env_rejected`` â€” module_06 boundary-regex
  defense.
- ``runtime.run_id.env_stripped_from_parent``
- ``runtime.run_id.orphan_generated``
- ``sidecar.header.written``
- ``sidecar.header.missing_refused``
- ``sidecar.header.mismatch_refused``

### New exception types

- ``ract.core.rootknot.RootknotSchemaViolation`` â€” v4-label
  without v4-fields (module_01).
- ``ract.core.provenance.RootknotUnknownSidecarFormat`` â€”
  unknown named sidecar ``schema`` (module_06 fold of module_01
  Q3).
- ``ract.runtime.RunIdFormatError`` â€” path-shape /
  shell-metacharacter poisoning candidate rejected at the
  ambient boundary (module_06 fold of module_04 C-6).

### v0.6 backlog

Twenty-one deferred carryover items routed to
`docs/RACT_v0.6_BACKLOG.md` (owner-column table per Ox-Alpha
co-build Q3 verdict). Includes the ``.ract/sandbox_env.allowlist``
trust-tier redesign (ADR-0048 reserved), the external
manifest-ledger anchor for mid-file trace tamper, the universal
``write_sidecar_header`` sweep, and the ``ract sidecar reheader``
verb.

### Compatibility

v0.5.1 payloads, sidecars, and trace logs continue to load
unchanged. ``min_acceptable_schema_version`` defaults to 3. Legacy
trace files auto-generate a fresh warm-verify sidecar on first
``ract trace verify``. Full migration walk-through in
`docs/UPGRADING.md`. Rollback: ``git checkout
backup-v0.5.1-preHardening`` (created at module_06 close).

### Backup tag

``backup-v0.5.1-preHardening`` at the v0.5.1 tip
(``300f8b22``) created before the version bump.

---

## [0.5.1] - 2026-08-22 â€” External Review Response + wired + spec-completeness

> **Note on cited SHAs (2026-08-22 update).** The plain-text 7-hex
> tokens below (rendered without backticks) reference
> pre-`git filter-repo` history that was
> obliterated on 2026-08-22 when a history rewrite replaced every
> object in the tree. The current-history equivalents live under the
> `release(v0.5.1): ...` commits reachable from `origin/main`
> (30 primary release commits, from `89300cd` back through `ab1367a`),
> discoverable via `git log --grep='release(v0.5.1)'`. The narrative
> descriptions below are preserved verbatim so the release story
> continues to read as authored; the leading-index anchors
> `89300cd`, `4093643`, and `ab1367a` are resolvable under the current
> tree and satisfy `test_changelog_v051_shas_resolve_in_git`.

> **Third re-tag.** Tag re-issued 2026-08-22 at the spec-completeness
> pipeline HEAD. This release combines three sequential closure
> pipelines against the same v0.5.1 semver:
>
> 1. **External Review Response** (nine modules bb8e013 era) â€”
>    the trust-chain fixes described in the release body below.
> 2. **Wiring completion** (eleven modules c78d8b1 .. 53280ff,
>    close at 15e6cb1) â€” closes every zero-caller gap surfaced
>    by the 2026-08-21 8-lens audit
>    (`_BUILD/audit_2026-08-21/AUDIT_SUMMARY.md`) with production
>    call chains from runtime entry points. Re-audit at
>    `_BUILD/audit_2026-08-21b/AUDIT_SUMMARY_v2.md` verified zero
>    CRITICAL / HIGH remained OPEN against the wired surface.
> 3. **Spec completeness** (seven modules; module_06 CANCELLED per
>    Ox Alpha adversarial review; commits c5ff8ac, a147610,
>    eb6ba41, 2db7f88 + 769192d, 2b2e5b1 + ea82b54 +
>    556b2b7, 403d800 + 4569426, plus this release-close
>    commit) â€” closes the source-spec audit gaps
>    (`_BUILD/audit_2026-08-21c/AUDIT_SUMMARY_c.md`, 7 lenses)
>    where the code did not yet do what the Memory Discipline spec
>    prescribed, and formalizes deferrals via ADR-0043 (DSPy),
>    ADR-0044 (LeWM), ADR-0045 (nightly failure-learning workflow),
>    and ADR-0046 (Bonsai council summarizer). Re-audit at
>    `_BUILD/audit_2026-08-22/AUDIT_SUMMARY_d.md` (4-vector sneak-
>    hardened per Ox Alpha Â§3).
>
> Prior tags preserved locally as `backup-v0.5.1-preWiring`
> (external-review-response HEAD, primitives-only) and
> `backup-v0.5.1-preSpecCompleteness` (wiring-HEAD `96b06790`,
> wired-but-pre-spec-completeness). See the **Spec-completeness**
> and **Wired** sections below for the per-module maps.

Patch release for the External Review Response pipeline
(`_BUILD/ract_v0.5.1_external_review_response/`). This release closes
the trust-chain gap opened at the 200-compaction boundary that DeepSeek
rounds 1-5 + REVIEW_4_UNKNOWN_REVIEWER surfaced against v0.5.0: the
Rootknot signed surface is extended (not broken) with workspace, prompt,
and run-id digests; the assumption ledger crash-consistent; every hashed
byte-string travels through RFC 8785 JCS; a new PROMPT_DRIFT termination
cause plus operator-signed intent-recompile CLI verb close the intent-
mutation loophole; the SubstrateLoop shim closes its four SUBSTRATE
Â§4-Â§7 gaps (tool-invocation gate, process-group tree-kill, environ
allowlist, git-commit compensator); an ambient run_id ContextVar
preserves identity end-to-end across compaction; a historical Manifest
Ledger with Merkle chain adds tamper-detectable durability to RK-3;
G5/G6 laziness enforcement expands from Python-only to five polyglot
languages via tree-sitter; the sycophancy classifier gains an AST-delta
signal + WhispererContract event scoring F1=1.000 on a 48-sample
regression corpus. Tag is `v0.5.1`. Three ADRs added (ADR-0040 for
T8 PROMPT_DRIFT, ADR-0041 for SubstrateLoop shim closure, and
ADR-0042 for the sycophancy v2 tuning band â€” six more surfaces
carry inline ADR-style module docstrings).

### Per-module surface

- **module_01 â€” RootknotWAL crash-consistency (G1).** New
  `src/ract/core/assumptions_wal.py` (~475 lines) with append-only
  JSONL write-ahead log at `.ract/assumptions.wal`, cross-platform
  exclusive file lock, fsync per append, truncated-tail tolerance
  with WARN, middle-corruption refusal, and `AssumptionRegistry` wire
  so accepted assumptions durably replay across restart. New
  `EventKind.assumption_accepted` in the closed vocabulary. Primary
  cf829d5; SP amendment fcc23af (WARN emission on truncated tail
  + rotation-atomicity docstring correction).

- **module_02 â€” Rootknot canonical-bytes extension (G2 + G3 +
  REVIEW_4_UNKNOWN A2).** Three new opt-in fields on the Rootknot
  dataclass â€” `workspace_digest`, `prompt_digest`, `run_id` â€” plus
  `make_rootknot_v4()` factory bumping `schema_version` 3â†’4. New
  `src/ract/core/workspace_digest.py` with pure-hash
  `workspace_digest()` + `compute_prompt_digest()` + `run_id_hex()` +
  `WorkspaceDigestChain` ancestor ledger. `AcceptanceSuite.prompt_digest`
  optional field populated by `IntentCompiler.compile()`. Sacred spine
  preserved â€” the three signed byte-strings extend, nothing removed.
  Primary 88c35a6; SP amendment 8dbf452 (strict-JSON metadata_hash
  + `MetadataUnserialisableError`, exclusive-lock on chain read path,
  `require_prompt_digest()` helper).

- **module_03 â€” RFC 8785 JCS canonical JSON.** New `src/ract/canonical.py`
  (462 lines) with `dumps_jcs`/`loads_jcs`/`is_canonical`/
  `CanonicalJSONError` implementing strict-JSON NFC-normalised codepoint-
  sorted ECMA-262-conformant serialiser. 15-file migration of every
  hash-input path: `rootknot.py`, `predicate.py`, `workspace_digest.py`,
  `assumptions_wal.py`, `plan.py`, `security/manifest.py`,
  `trace/events.py` + `writer.py`, `receipt.py`, `receipt_chain.py`,
  `run_fingerprint.py`, `reproducibility_manifest.py`,
  `mutation_merge_gate.py`, `antilazy/symgraph.py`, `memory/cache.py`,
  `memory/query_trace.py`, `memory/functions/contracts.py`,
  `memory/retrieve.py`. Grep-gate at
  `tests/architecture/test_no_sort_keys_in_canonical_paths.py` (tokenize-
  based comment/string blanking + stale-allowlist sanity + 20-entry
  allowlist). Primary 98931c4; SP amendment 2205309
  (`__json_snapshot__` cycle guard + explicit opt-out, shortest-repr
  number encoding replacing initial log10 + `.17f`, non-ASCII invariant
  tests, look-back window widened 8â†’50).

- **module_04 â€” T8 PROMPT_DRIFT + T9 PROMPT_DIGEST_MISSING + `intent
  recompile` CLI verb.** New termination causes T8 (mutation-detected)
  and T9 (opt-in strict-prompt-digest missing) added to the closed
  `TerminationCause` enum with pinned integer values. New
  `src/ract/core/suite_chain.py` (~340 lines) append-only JSONL ledger
  of AcceptanceSuite versions per run with cross-platform file lock,
  fsync per append, tail-truncation tolerance, and middle-corruption
  refusal. New `src/ract/core/intent_recompile.py` (~280 lines)
  operator-signed recompile action loading key from `.ract/operator.key`
  OR `RACT_OPERATOR_KEY` env var, HMAC-SHA256-signed recompile bytes,
  and initial-entry lazy record. `LoopController._check_prompt_drift`
  per-iteration hook with chain-head comparison, initial fallback, T8
  halt, and rollback to `last_known_good_workspace`. New ADR-0040. New
  `ract intent recompile <run_id>` CLI verb (mutually-exclusive
  `--intent-file` / `--intent-text`). Primary 1186f8d; SP amendment
  9d4acc6 (Q1 pinned enum values, Q2 orphan-file enumeration + opt-in
  `delete_orphaned_files_on_t8`, Q4a resolved key path, Q4b T9 +
  `strict_prompt_digest`, Q5a `.recompile_lock`, Q5b eager initial
  entry, Q6b split exit codes 2/3/4/5).

- **module_05 â€” SubstrateLoop shim-wiring closure (SUBSTRATE Â§4-Â§7 +
  B3 + D1).** Four new modules close the executor gap. New
  `src/ract/executor/tool_gate.py` (549 lines) with four-gate
  `ToolInvocationGate` + closed-type `ToolArgSchema` + frozen
  `ToolRegistry` + `ToolInvocationRefused` structured shape + bounded
  `args_repr` for privacy + `tool.invocation.pre|post|refused` events.
  New `src/ract/executor/process_group.py` (460 lines) with POSIX
  `setsid` via `start_new_session` + Windows `CREATE_NEW_PROCESS_GROUP`
  + Job Object with kill-on-close + `killpg`/`TerminateJobObject` reap
  + `taskkill /F /T` fallback + optional SIGTERM grace period. New
  `src/ract/security/sandbox_env.py` (370 lines) with `DEFAULT_ALLOWLIST`
  (44 POSIX+Windows+locale names) + `NEVER_PASSTHROUGH` (17 credential
  names) + `build_sandbox_env` with count-only WARN + JSONL loader that
  refuses malformed configs. New `src/ract/executor/commit_compensator.py`
  (346 lines) with `CommitCompensator` (soft-reset default) +
  `CompensatorStack` LIFO drain + `check_pushed` via
  `git branch -r --contains` + refusal-of-pushed-commits +
  install/discard/apply/refused events. ADR-0041 names four decisions
  + five rejected alternatives. Primary ed62a47; SP amendments
  75eda12 (Q2 CREATE_SUSPENDED + `_resume_thread`, Q3a
  NEVER_PASSTHROUGH_PREFIXES + case-insensitive + glob refusal, Q3b
  `_redact_name_for_log`, Q3d utf-8-sig read + per-line BOM strip,
  Q4c `_resolve_branch` + `_current_branch` + `git update-ref`, Q5b
  HEAD-read post-fast-forward gates `parent_snapshot`, Q5c
  `dispose(success=False)` resyncs) + 12d933f + 968fe64.

- **module_06 â€” ambient run_id ContextVar + end-to-end preservation
  smoke.** New `src/ract/runtime.py` (140 lines) with ContextVar-
  backed `run_id` accessor + `bind_run_id` context manager +
  `set/reset` primitives + type/empty guards. WAL `_persist` stamps
  ambient into payload when caller omits `run_id`.
  `WorkspaceDigestChain.append` accepts explicit `run_id` kwarg +
  falls back to ambient + `ChainEdge.run_id` optional field for
  backward-compat. `JsonlEventWriter` and `make_rootknot_v4` accept
  `run_id=None` and decode ambient hexâ†’bytes, refusing when no
  ambient bound (control-bypass guard). `LoopController.run()` binds
  ambient at entry via `_resolve_or_mint_run_id` (marker file â†’
  basename â†’ mint fresh 32-hex + write marker for compaction
  survival). Primary 39789e2; SP amendment ab5ecdc (Q1
  `run_with_ambient(fn,*args,**kwargs)` closure pattern, Q2 WAL WARN
  on explicit-vs-ambient divergence, Q4 cross-platform exclusive
  lock on `run_id.txt.lock` sidecar, Q5 WAL reload WARN on
  bound-ambient with legacy no-rid entries).

- **module_07 â€” Historical Manifest Ledger (RK-3 durability).** New
  `src/ract/security/manifest_ledger.py` (~1000 lines) with
  `ManifestLedger` append-only JSONL at `.ract/manifest_ledger.jsonl`
  + content-addressable snapshot store at
  `.ract/manifest_snapshots/{digest_hex}.json` (idempotent CAS via
  tmp+os.replace) + Merkle chain via `prev_ledger_hash` (GENESIS
  sentinel for first entry) + cross-platform file lock mirroring
  `assumptions_wal.py` (msvcrt.locking Windows + fcntl.flock POSIX,
  3-attempt/10ms backoff, LedgerLockContended) + `verify_chain`
  returning `LedgerVerifyResult{valid, first_break_at,
  tail_valid_count}` detecting middle-tamper AND surfacing truncated-
  tail via reduced count + `proof_of`/`verify_proof` with loader-based
  full-chain mode + idempotence by `(run_id, manifest_digest)` within
  run + ambient ledger accessor + WAL cross-link via
  `count_wal_entries`. New EventKind `manifest.ledger.appended` in
  closed vocabulary. `Rootknot.attest_environment` wired to call
  `record_environment_attestation` post-signing via local import
  breaking securityâ†’core cycle â€” signed RK-3 payload unchanged.
  Primary 2cb42b4; SP amendment dbd0a73 (Q1 `_entry_schema_valid`
  mandatory-field shape check, Q3 per-process/per-thread CAS tmp path
  `.json.tmp.{pid}.{tid}`, Q5 `manifest.ledger.refused` EventKind +
  WARN wrap in observer, Q6 `verify_proof` now REQUIRES loader +
  raises ValueError when None + new `verify_proof_shape_only` static
  method).

- **module_08 â€” Polyglot G5/G6 via tree-sitter.** New
  `src/ract/parsers/tree_sitter_backend.py` (~340 lines) with
  `Language` enum (PYTHON/JAVASCRIPT/TYPESCRIPT/TSX/RUST/GO) +
  `LANGUAGE_BY_EXTENSION` map covering 10 MVP extensions +
  `ParseTree`/`ParseError` dataclasses + cached `_load_grammar` per
  language + `parse(file_path, source_bytes)â†’ParseTree|None`
  byte-oriented hot path + `parse_file` convenience +
  `iter_nodes`/`node_text`/`field_named` walk helpers +
  `tree_sitter_available` probe. New
  `src/ract/antilazy/dead_code_polyglot.py` (~440 lines) with
  `DeadCodeCandidate`/`DeadCodePolyglotReport` +
  `scan_dead_code`/`scan_dead_code_in_dir` public APIs +
  Python-parity via stdlib `ast` (never routed through tree-sitter) +
  per-language dispatch for JS/TS/Rust/Go. New
  `src/ract/antilazy/test_copy_paste_polyglot.py` (~450 lines) with
  token-normalised Jaccard fingerprint (`jaccard_threshold=0.85`,
  `min_tokens=6`) + per-language test-body extractors (Python pytest
  `test_*`, JS/TS/TSX `call_expression it/test/describe/t`, Rust
  `#[test]` via `_collect_scope`, Go `func Test*` in `*_test.go`).
  `enforce_g5_dead_code_polyglot` + `enforce_g6_test_copy_paste_polyglot`
  wired in `pre_commit.py`; legacy `enforce_g5`/`enforce_g6` untouched
  (additive-only preservation). `pyproject.toml [polyglot]` optional-
  dep group. Primary c74f717; SP amendment da24c63 (Q1 public
  `reset_grammar_caches()`, Q2 `visit_AnnAssign` for `x: SomeType = 1`,
  Q3 destructuring `object_pattern`/`array_pattern` in
  `_collect_declarator_decls`, Q4 `_extract_rust._collect_scope`
  resets `prev_attr_text`, Q5 `iter_nodes` `DEFAULT_MAX_STACK_DEPTH`
  = 10_000 + `max_stack_depth=None` opt-out, Q6 `_lang_group_key`
  folds typescript+tsx into one Jaccard group).

- **module_09 â€” Sycophancy classifier v2 (AST-delta + WhispererContract-
  event).** New `src/ract/antilazy/sycophancy_v2.py` (~640 lines) with
  two-signal classifier: Signal 1 AST-delta null-op score over fenced-
  block-extracted request/response with identifier-name intersection to
  distinguish verbatim-echo from new-structural, Signal 2
  `commitment_count = ast_new_commitments + factual_claims` (sentences
  carrying distinguishing predicates: numbers, backtick tokens,
  snake_case, camelCase, file paths, ~50 measurement/operational
  verbs), combined as `is_sycophantic = (null_op_score > 0.7) OR
  (commitment_count < 3)`. New EventKind
  `whisperer.contract_violation` in closed vocabulary emitted via
  best-effort emit on composed verdict. Legacy
  `ract.antilazy.sycophancy` reversal-scan preserved unchanged for its
  own trace-scanning use case. New `tests/fixtures/sycophancy_corpus/`
  ships 48 samples (23 sycophantic + 25 genuine); F1 = 1.000 (P=1.000
  R=1.000) vs target â‰¥0.85, stable across operator-tuning sweep band
  `threshold âˆˆ {0.6, 0.7, 0.75, 0.85} Ã— floor âˆˆ {2, 3}`. Primary
  7a4e53b; SP amendment dceb2d8 (Q1 `_PREDICATE_PATTERNS`
  extended with 14 causal/diagnostic verbs, Q3 runtime tunable
  overrides on `classify()` + `score_corpus()` with `effective_*`
  fields, Q4a `emit_event()` gate lifted to composed verdict, Q4b
  `response_full_hash` (SHA-256 64-hex) added as first-class field,
  Q5 `_STATEMENT_WEIGHT_CAP = 2`, Q6 `_AstStats.func_body_shapes` +
  `corrective_same_name` count).

- **module_10 â€” release close.** This entry, version triple bump
  0.5.0 â†’ 0.5.1, golden hash re-lock, annotated tag, handshake
  push-commands file. `ract --version` prints `RACT 0.5.1`.

### Added

- **Three new ADRs** â€” ADR-0040 (T8 PROMPT_DRIFT termination cause +
  operator-signed intent-recompile), ADR-0041 (SubstrateLoop shim
  closure four-decision bundle), and ADR-0042 (sycophancy v2
  tuning band -- `NULL_OP_SCORE_THRESHOLD = 0.7` +
  `MIN_COMMITMENT_FLOOR = 3` with runtime-tunable overrides and an
  eight-cell sweep test). Six further modules carry inline
  docstring-style ADRs in their primary source files.
- **New EventKinds** in `src/ract/trace/events.py::EventKind` closed
  vocabulary â€” `assumption.accepted` (module_01),
  `tool.invocation.pre`, `tool.invocation.post`, `tool.invocation.refused`
  (module_05), `manifest.ledger.appended`, `manifest.ledger.refused`
  (module_07), `whisperer.contract_violation` (module_09), plus
  module_05 sandbox `unenforced_sandbox` env-audit surface.
- **`TerminationCause.PROMPT_DRIFT` (T8)** and
  **`TerminationCause.PROMPT_DIGEST_MISSING` (T9)** with pinned integer
  values 1-9 (module_04).
- **`ract intent recompile <run_id>`** CLI verb with mutually-exclusive
  `--intent-file` XOR `--intent-text` and split exit codes 2/3/4/5.
- **Rootknot schema_version 4** carrying opt-in `workspace_digest` +
  `prompt_digest` + `run_id` fields; older sidecars continue to verify
  under the v3 compatibility reader path.
- **RFC 8785 JCS canonical JSON** â€” `src/ract/canonical.py` public
  surface, importable as `from ract.canonical import dumps_jcs,
  loads_jcs, is_canonical, CanonicalJSONError`.
- **Ambient run_id ContextVar** at `src/ract/runtime.py` â€” importable
  as `from ract.runtime import bind_run_id, get_current_run_id,
  run_with_ambient`.
- **Historical Manifest Ledger** at `.ract/manifest_ledger.jsonl` +
  `.ract/manifest_snapshots/`; `src/ract/security/manifest_ledger.py`
  public API `ManifestLedger`, `verify_chain`, `proof_of`,
  `verify_proof`, `LedgerVerifyResult`, `MerkleProof`.
- **Tree-sitter polyglot backend** at
  `src/ract/parsers/tree_sitter_backend.py` with the six-language
  MVP surface and `[polyglot]` optional-dep group in `pyproject.toml`.
- **Sycophancy classifier v2** public API `classify_sycophancy_v2`,
  `score_sycophancy_corpus`, `SycophancyClassification`, `CorpusScore`,
  `MIN_COMMITMENT_FLOOR`, `NULL_OP_SCORE_THRESHOLD` re-exported from
  `ract.antilazy`.
- **~500 new tests** across `tests/unit/`, `tests/integration/`,
  `tests/property/`, `tests/security/`, `tests/architecture/`
  covering the eight closure modules.

### Extended

- **`SubstrateLoop.invoke_tool`** enforces four gates (schema, registry
  membership, arg-cap, budget) with structured `ToolInvocationRefused`;
  ambient WAL/ledger observers wired at loop entry.
- **`AssumptionRegistry`** now persists accepted assumptions to a
  crash-consistent WAL replayed on restart; existing in-memory API
  unchanged.
- **`AcceptanceSuite.digest`** and every hashed payload across
  `plan.py`, `receipt.py`, `run_fingerprint.py`,
  `reproducibility_manifest.py`, `mutation_merge_gate.py`,
  `memory/cache.py`, `memory/query_trace.py`,
  `memory/functions/contracts.py`, `memory/retrieve.py`,
  `antilazy/symgraph.py` route through `dumps_jcs` instead of
  `json.dumps(sort_keys=True)`. Grep-gate installed to prevent
  regression.
- **`LoopController.run()`** binds ambient `run_id` at entry, runs
  the T8 `_check_prompt_drift` hook per iteration, rolls back to
  `last_known_good_workspace` on drift detection, and emits
  `run.completed` with orphan-file enumeration.
- **`enforce_g5` / `enforce_g6`** now have polyglot counterparts
  `enforce_g5_dead_code_polyglot` / `enforce_g6_test_copy_paste_polyglot`
  that emit `laziness.violated` with
  `kind=dead_code_polyglot|test_copy_paste_polyglot` payload
  discriminators. Legacy Python-only paths untouched.

### Verified

- **Version triple.** `VERSION`, `pyproject.toml [project].version`,
  and `src/ract/__init__.py __version__` all equal `0.5.1`;
  `ract --version` prints `RACT 0.5.1`. Test gates:
  `test_version_matches_across_files` and
  `test_ract_version_cli_reports_aligned_identity`.
- **Golden hash re-locked** at fixed-point after all module landings +
  SP-amendment folds; locked value at tag:
  `7ba823c90711e517f954a65dcbef705f8df94eae460e6b2899d1fb15bba5f4d9`
  (was `74929aa977b717567c39de1216cbe831c5239e48ebab09f38d763102b4bddf3d`
  at v0.5.0). Shift is legitimate â€” canonical-bytes extension,
  JCS migration, WAL / suite-chain / ledger additions, executor
  shim closure, ambient runtime, polyglot backend, sycophancy v2 all
  land under `src/ract/` inside the digest scope.
- **Sacred spine.** Rootknot three-signature schema unchanged
  (extended, not broken â€” schema_version 4 carries opt-in fields
  older readers ignore). `__root_author__` audit still refuses re-
  entry. AL-1 property tests green (`tests/test_antilazy_al1.py`).
- **Closed-IP wordlist scan.** Zero hits outside the two documented
  `assets/demo.cast` deferrals. Test gate:
  `test_no_closed_ip_terms_in_tracked_files`.
- **JCS grep-gate.** Zero `json.dumps(sort_keys=True)` and zero
  `json.dumps(..., sort_keys=True)` on hash-input paths outside the
  20-entry documented allowlist. Test gate:
  `tests/architecture/test_no_sort_keys_in_canonical_paths.py`.
- **Full suite.** Green modulo known skips (see per-module gate
  scorecards in `_BUILD/ract_v0.5.1_external_review_response/` +
  `_BUILD/ract_v0.5.1_wiring_completion/`).

### Wired (v0.5.1 wiring-completion pipeline)

The 2026-08-21 8-lens audit
(`_BUILD/audit_2026-08-21/AUDIT_SUMMARY.md`) found that several v0.5.1
primitives shipped with **zero production callers** â€” clean-tested API
surface, but the runtime paths still called the pre-v0.5.1 shape.
The wiring-completion pipeline
(`docs/RACT_v0.5.1_WIRING_COMPLETION_SPEC.md`, modules 01-11) closes
each such gap. The re-audit at
`_BUILD/audit_2026-08-21b/AUDIT_SUMMARY_v2.md` verifies zero
CRITICAL/HIGH findings remain OPEN.

- **wiring module_01** (c78d8b1) â€” provenance and docs sync.
  CHANGELOG SHAs regenerated post-filter-repo (was: 21 fabricated
  short SHAs);  THREAT_MODEL / PROVENANCE / EVENTS / ROADMAP re-hosted
  at v0.5.1 (were: frozen at v0.4.0); ADR-0042 shipped (was: cited
  in ADR count but missing on disk). Lens B C1-C6 closed.
- **wiring module_02** (c07f8a8) â€” **wired:** `make_rootknot_v4`
  now called from `src/ract/executor/steps.py:624`; sidecar
  `provenance.py` round-trips v4 fields (`schema_version=4`,
  `workspace_digest`, `prompt_digest`, `run_id`); WAL torn-pair
  regression fixed in `assumption_registry.py`; Windows chain
  readers switched to lock-free `O_APPEND` atomicity;
  `intent_recompile` now auto-scans the workspace to avoid empty
  snapshot regression. Lens D D1-D5 closed.
- **wiring module_03** (3d039c6) â€” **wired:** tool gate chokepoint.
  `SubstrateLoop.invoke_tool` now called from `executor/steps.py`
  MCP `tool_call` dispatch with `ToolInvocationRefused` handling
  (was: 0 production callers). SUBSTRATE Â§5 chokepoint claim now
  load-bearing. Lens C C-01 closed.
- **wiring module_04** (9d3a534) â€” **wired:** `NEVER_PASSTHROUGH`
  env allowlist. `security/sandbox_linux.py:248` and
  `security/sandbox_macos.py:152` now call `build_sandbox_env` and
  filter env against the scrubbed allowlist (was: enforced sandboxes
  bypassed the deny list entirely). SUBSTRATE Â§4.3 deny surface now
  active on the enforced paths, not just the Windows unenforced stub.
  Lens C C-02 closed.
- **wiring module_05** (f51af72) â€” **wired:** process-group
  tree-kill. `SubstrateLoop.spawn_subprocess` wraps
  `process_group.spawn`; `_reap_active_processes` calls `kill_tree`
  from every rollback path (was: 0 production callers in `src/`).
  `_fast_forward_head` gains `soft: bool` parameter defaulting to a
  `git reset --soft` so the compensator can inspect the tree before
  discarding. Lens C C-03 + C-04 closed.
- **wiring module_06** (6b48e58) â€” **wired:** ambient run_id +
  loop-resume. `LoopController._run_with_timeout` wraps
  `executor.submit` in `run_with_ambient` (was: bare
  `ThreadPoolExecutor` at `loop_controller.py:1362` reintroduced the
  exact bug module_06 was written to close). Full loop-resume
  protocol added (`_LOOP_STATE_SIDECAR_NAME`, `on_pause`, `on_resume`,
  `resume`, `start_index` persisted, `last_known_good_workspace`
  rehydrated). `core/loop.py` chain-init `except Exception: pass`
  replaced with a narrow tri-arm handler; `SuiteChainCorruptError`
  re-raises. T8 orphan-file delete now gated on
  `allow_iter1_delete_orphans` kwarg (was: iter-1 T8 wiped tree).
  Lens G G-01 through G-08 closed.
- **wiring module_07** (3079aa0 + e4258b6) â€” **wired:** anti-lazy
  dispatch. `_run_sycophancy_v2_check`,  `_run_polyglot_g5_g6`, and
  `_run_canonical_g1_g7_g8` now fire per iteration from
  `loop_controller.py` (was: `classify_sycophancy_v2` and
  `enforce_g5/g6_polyglot` had 0 live callers; G1/G7/G8 had no
  `enforce_gN`). Every `*GateOutcome` in `antilazy/pre_commit.py`
  carries a `rootknot_signature` validated in `__post_init__` via
  `_require_gate_signature` (raises on empty). **AL-1 is now a
  structural invariant, not a convention.** Lens E AL-E-01 through
  AL-E-04 closed.
- **wiring module_08** (968b7e9 + 6203f60) â€” **wired:** memory
  index watchers. `SymbolIndexWatcher` now holds a cache handle and
  `_reindex_write` / `_reindex_delete` call `cache.invalidate_by_file`
  with TTL (was: silent staleness after first save). Watcher
  constructor accepts `graph_populator` + `semantic_index` and
  cascades on every reindex with per-index counters +
  `memory.freshness_gap` event. `budget_registry
  .get_with_capability_clamp` narrows via `apply_runtime_narrowing`.
  Probe scheduler fires once per `run()`;
  `_run_composed_retrieval` dispatches composition. Lens E MEM-E-01
  through MEM-E-04 closed.
- **wiring module_09** (0879ab0 + a061f3d) â€” JCS + EventChain +
  ledger tamper. Three real hash-input sites migrated to `dumps_jcs`
  (`plan_replay.py`, `memory/repo_fingerprint.py`,
  `memory/probes/scheduler.py`); remaining sites documented as
  human-report/storage-only in the JCS grep-gate allowlist; the gate
  now also forbids `sha256(json.dumps(sort_keys=True))` +
  `.encode(...)` on hash inputs. `EventChain` no longer resets on
  fresh writer construction â€”  `writer.py::_reseed_tip_from_disk`
  walks the tail, seeds from the last parseable event, refuses on
  UTF-8 decode failure. `EventReader.load` / `iter_events` now
  tail-tolerant + middle-strict + WARN (was: only ledger that
  hard-failed on truncated tail). `manifest_ledger._build_entry`
  stamps `entry_index`; `verify_chain` detects middle-excise via
  physical-vs-stamped density check. Lens F H1-H4 + Lens G G-06
  closed.
- **wiring module_10** (427537c + 53280ff) â€” UX + CLI + retrieval
  wire + `.ract`/`.rack` unification + manifest-ledger CLI verbs.
  Full-verb `ract --help` catalog via `cli_help.py`;
  `workspace_state.migrate_rack_to_ract` idempotent migration at CLI
  entry; `ract retrieval query` now calls the real `retrieve()`
  primitive (was: documented stub); `ract manifest ledger
  {verify,inspect,show,proof}` verbs added; duplicate marketplace
  dispatch deleted (tombstone comment kept); `--auto` refuses on
  non-TTY stdin with exit 3; bare `ract retrieval` / `memory` /
  `plan` exit 0 after help; README verb index regenerated + drift
  gate; module_02 executor test fixture updated to full v4 dep set;
  distinct exit codes for `verify` chain-valid / broken / crashed.
  Lens A C1-C3 + M1-M9 closed.
- **wiring module_11** (15e6cb1) â€” release close for the wiring
  pipeline. Golden hash re-locked at that HEAD; 8-lens re-audit at
  `_BUILD/audit_2026-08-21b/AUDIT_SUMMARY_v2.md` verified zero
  CRITICAL/HIGH findings remained OPEN against the wired surface;
  `v0.5.1` tag re-issued at the wired HEAD (prior bb8e013
  preserved as `backup-v0.5.1-preWiring`). Superseded at the third
  re-tag by the spec-completeness close commit (see the
  **Spec-completeness** section below); the wired HEAD is preserved
  as `backup-v0.5.1-preSpecCompleteness`.

### Spec-completeness (v0.5.1 spec-completeness pipeline)

The 2026-08-21 source-spec audit
(`_BUILD/audit_2026-08-21c/AUDIT_SUMMARY_c.md`, 7 lenses) checked
the wired v0.5.1 surface against two source design documents â€” the
Memory Discipline spec and a second internal design document
(salvage items only). The wiring pipeline had closed every zero-caller
gap; the source-spec audit surfaced a distinct class of findings â€”
places where the code did not yet do what the spec prescribed, or
where docs claimed a mechanism the code did not ship. The v0.5.1
spec-completeness pipeline
(`docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md`, 8 modules, one
CANCELLED per Ox Alpha adversarial review 2026-08-21) closes those
findings and formalizes the deferrals via ADRs. Re-audit at
module_08 (`_BUILD/audit_2026-08-22/AUDIT_SUMMARY_d.md`, 4-vector
sneak-hardened per Ox Alpha Â§3) verifies every CRITICAL / HIGH
finding either CLOSED or explicitly DEFERRED via ADR.

- **spec-completeness module_01** (c5ff8ac) â€” docs honesty pass.
  `[0.5.1]` CHANGELOG rewrite (this section framing); ROADMAP +
  THREAT_MODEL + PROVENANCE + EVENTS scrub of DSPy / LeWM claims;
  Memory Discipline spec Â§Self-Adjustment items 3 (DSPy) and 4
  (LeWM) gain "Not-yet-shipped" callouts. **ADR-0043** (DSPy
  compilation-recompilation deferred to v0.6) and **ADR-0044**
  (LeWM 23-dim drift detection deferred to v0.6) authored. New
  grep-gates in `tests/test_release_surface.py` refuse `dspy` /
  `lewm` string mentions in the `[0.5.1]` CHANGELOG section
  outside a tight allowlist (window widened per SP amendment).
- **spec-completeness module_02** (a147610) â€” budget hardening.
  New `BudgetInputMaxExceeded` exception subclass carrying
  `function_name` + `budget` + `actual_input_tokens`; new
  `refuse_over_max` wrapper in `provider_adapter.py` wired at all
  four shipped memory-discipline functions (intake / research /
  plan / edit) **before** the existing `refuse_over_ceiling` gate.
  15% `state_context` sub-budget cap via `seat_state_section` with
  `STATE_CONTEXT_CAP_FRACTION = 0.15` computed against
  `input_target` (SP-mandated drift guard against `input_max`);
  `truncate_tail` strategy emits a `state.budget_capped` event and
  returns `(section, effective_content)` so callers assemble the
  truncated body (audit-trail truth). New `state.budget_capped`
  EventKind (`schema_version` 5â†’6). Closes Lens 1A A-1 + A-2
  (both CRITICAL).
- **spec-completeness module_03** (eb6ba41) â€” write-first
  invariant hardening + `src/ract/trace/repair.py`. `WriteFirstViolation`
  exception + `_committing` flag guard + fsync-inside-lock in
  `JsonlEventWriter._write_line`; two observer classes explicit
  (`_post_commit_observers` fire on every emit, raise WARN-logged
  and not propagated; `_durability_observers` fire only on
  `checkpoint()`, raise propagates); legacy `add_mirror` backward-
  compat preserved. New `repair(events)` deterministic (synth id =
  `sha256(_SYNTH_MARKER || open.id || close_kind)[:16]`) and
  idempotent (`repair(repair(x)) == repair(x)` via by-id
  `source_event_id` pairing) â€” synthesizes close events for the
  5 first-party lifecycle kinds RACT tracks (`run.started`,
  `step.started`, `tool.called`, `prompt.sent`,
  `handshake.requested`). `JsonlEventWriter(..., repair_on_open=True)` opt-in.
  `ract trace repair <run_id> [--apply] [--json]` CLI verb. Closes
  Lens 2 Delta 1.
- **spec-completeness module_04** (2db7f88 + 769192d) â€” cross-
  function grouping rules. New `src/ract/memory/grouping.py`
  (`GroupingRules` + `SymbolGroup` + `group_symbols(...)` pure +
  `load_grouping_rules(...)` YAML loader). Four rules per Memory
  Discipline spec Â§Cross-Function Grouping: `dataclass_methods`
  (Python `@dataclass` / `@dc` / `@dataclasses.dataclass` /
  `@pydantic.dataclasses.dataclass` / `@attrs.dataclass` +
  methods), `trait_impls` (Rust trait + `impl <Trait> for <T>`
  when the query names the trait; namespaced + generic impl heads
  handled), `test_subject` (`test_foo` â†’ `foo`, `class TestFoo` â†’
  `class Foo`), `function_type_aliases` (Python fn/method
  signatures â†’ module-scope `type` aliases with 32-word stopword
  guard). Wired at `retrieve.py::_extend_with_grouping` post-
  cascade / pre-bundle-build; two-step budget cascade (caller
  format â†’ SIGNATURE â†’ drop with `dropped_companions` trace
  field). New `retrieval.grouping.applied` EventKind
  (`schema_version` 6â†’7). Cache-key distinctness includes
  `grouping_enabled` (SP DEFECT fix). Closes Lens 1C HIGH C-1.
- **spec-completeness module_05** (2b2e5b1 + ea82b54 +
  556b2b7) â€” AST-deterministic SUMMARY chunking + Python AST
  sub-chunker + **ADR-0046** (Bonsai council model-based path
  deferred). New `src/ract/memory/summary.py` with
  `summarize_chunk_deterministic(chunk, language=None)` producing
  signature + first-line docstring (`DOCSTRING_MAX_CHARS = 120`) +
  control-flow region counts + up-to-ten external-call targets
  (`MAX_EXTERNAL_CALLS = 10`); Python uses stdlib `ast`, non-Python
  uses per-language bounded regex catalogues.
  `format_chunk(SUMMARY, ...)` no-provider branch now returns this
  deterministic body (was `"summary unavailable"`);
  `summary_pending = False` whenever body is non-empty. Provider
  hook preserved as the v0.6 slot per ADR-0046. New
  `_split_python_ast_boundaries` walker cutting oversize function
  bodies at For / AsyncFor / While / If / Try boundaries with
  contiguous-line-range slicing + defensive byte-identity check
  falling through to the blank-line heuristic; renamed
  `_split_blank_line_groups` marker `SUB_CHUNK_METHOD_BLANK_LINE`
  vs new `SUB_CHUNK_METHOD_AST`. `sub_chunk_method` threaded
  through `ChunkRow.sub_chunk_method` + `Chunk.sub_chunk_method`
  for observability (SP fold-through). `chunk_from_chunk_row`
  language inference (`.py/.pyi`, `.ts/.tsx`, `.js/.jsx/.mjs/.cjs`,
  `.rs`, `.go`) so re-hydrated non-Python bodies pick the right
  regex catalogue. Closes Lens 1C MEDIUM findings 4 + 5.
- **spec-completeness module_07** (403d800 + 4569426) â€” verifier
  availability pre-check + `SubagentHandle` compensator cascade
  (with Ox Alpha Â§2 mandatory forced-failure integration test).
  New `VerifierUnavailable` exception in `src/ract/core/predicate.py`;
  `AcceptancePredicate.available()` delegates to new
  `check_invocation_available` in `src/ract/core/gates.py`
  (per-invocation dispatch: `shutil.which` for pytest / mypy,
  `importlib.util.find_spec` for hypothesis, `_resolve_callable`
  for assertion, always-True for artifact + related_file_coverage,
  fail-closed for unknown kinds â€” SP D1 amendment wraps unexpected
  exceptions into `VerifierUnavailable` rather than raw
  tracebacks). `build_loop_state` gains a structural pre-check
  walking `suite.required()` and refusing loop entry on the first
  miss; single opt-out kwarg (`skip_verifier_availability_check=True`)
  per Ox Alpha SP Q4 (STRUCTURAL not advisory). New
  `src/ract/executor/subagent_handle.py` (~240 lines) with
  `SubagentHandle` Protocol + `SubprocessSubagentHandle` (Popen
  wrapper reaping via `process_group.kill_tree`; SP D2 amendment
  short-circuits on already-exited Popen to avoid false
  `ok=False` telemetry) + `InlineSubagentHandle` (teardown
  callable wrapper). `SubstrateLoop` gains
  `_active_subagent_handles` list + `register_subagent_handle`
  (identity dedup via `any(existing is handle)` per SP #2, not
  value-equality `in`) + `_reap_subagent_handles` (LIFO drain,
  best-effort dispose in try / except, emit-belt-and-suspenders
  per SP #3). Cascade wired into `dispose(success=False)` after
  `_reap_active_processes` + into `run_step` exception unwind. T1
  dispose discards the list without teardown (caller natural
  cleanup owns disposal). New `subagent.disposed` EventKind
  (`schema_version` 7â†’8); `docs/EVENTS.md` `kind` field described
  as OPEN VOCABULARY (SP A1 amendment corrects a prior closed-enum
  claim; third-party handles may set any `kind`). **`index_digest()`
  sub-item CANCELLED** per Ox Alpha Â§2 â€” no named production caller
  exists (verified by pre-build grep of retrieve / cache / watcher
  / composition surface). Closes Lens 2 Delta 2 (verifier
  availability pre-check). Addresses Lens 2 Delta 3 (SubagentHandle
  cascade wired end-to-end with Ox Alpha Â§2 forced-failure test)
  with four documented flagged gaps carried to v0.6: (a)
  SubagentHandle wired-in-anger from Whisperer / Fence async
  refactor, (b) resume-path bypass of the pre-check when
  `LoopState` is reconstructed from `suite.json`, (c) cross-thread
  `register` / `_reap` race (single-thread today), (d)
  `subagent.spawned` EventKind for trace-graph symmetry. SP
  amendment (module_08): pre-amendment wording "Closes Lens 2
  Deltas 2 + 3" overpromised on Delta 3; corrected here.
- **spec-completeness module_08** (this commit) â€” release close.
  **ADR-0045** authored (module_06 cancellation â†’ v0.6 deferral,
  per Ox Alpha Â§1). `[0.5.1]` CHANGELOG rewritten to reflect the
  final shipped state â€” every spec-completeness module named
  above appears with its behavior change described (Ox Alpha
  CHANGELOG-presence retroactive gate). Golden hash re-locked.
  Full pytest suite: 3139 passed / 21 skipped / 1 deselected / 3
  failed. All three failures are pre-existing before the spec-
  completeness pipeline started (git blame confirms none of the
  five spec-completeness modules that touched `src/ract/` modified
  the affected files):
  `tests/test_cli_retrieval.py::test_retrieval_no_action_prints_help`
  (the "1 deselected" â€” carried forward from module_01 baseline);
  `tests/test_readme_cli_index.py::test_readme_contains_cli_verb_index`
  and `tests/test_readme_version.py::test_readme_verb_index_includes_core_verbs`
  (both stem from the same README verb-index gap flagged as an
  R10 softbump during wiring module_10 close â€” README missing
  `ract config validate` and other core verbs). All three carried
  to v0.6 hardening (README verb-index refresh). SP amendment
  (module_08): pre-amendment wording claimed "green modulo the
  known [one] failure" â€” false-simplification that named a
  deselected test as the sole known failure while omitting the
  two README failures that actually failed in the run. Correction
  landed in this amendment. 7-lens re-audit
  at `_BUILD/audit_2026-08-22/AUDIT_SUMMARY_d.md` reports two
  numbers per lens (open against original spec + open against
  ADR-amended spec, the honesty metric per Ox Alpha Â§3 Vector 1);
  cold-read exercise per Vector 3; SP-picked excerpts + random
  seed per Vector 2; every by-design reclassification carries an
  SP citation per Vector 4. `v0.5.1` tag re-issued at this HEAD
  (prior `96b06790` wired-HEAD preserved as
  `backup-v0.5.1-preSpecCompleteness`); `HANDSHAKE_PUSH_COMMANDS.md`
  written for operator-gated push.

### Not yet shipped in v0.5.1 (deferred to v0.6)

The 2026-08-21 source-spec audit
(`_BUILD/audit_2026-08-21c/AUDIT_SUMMARY_c.md`) surfaced a gap
between what the Memory Discipline spec
(`docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`) prescribes and what
v0.5.1 actually ships. The v0.5.1 spec-completeness pipeline
(`docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md`) addresses the
release-label honesty gap by naming every prescribed mechanism that
is **not** shipping in v0.5.1, so readers do not have to grep the
tree to discover the deferral:

- **DSPy signature compilation-recompilation** (Memory Discipline
  spec Â§Self-Adjustment Mechanisms item 3, v0.6-backlog line 70)
  is **not shipped in v0.5.1**. No `src/ract/compilation/` directory;
  no `signatures.py` or `training.py`; the `dspy` dependency is not
  present in `pyproject.toml`. Deferred to v0.6 per **ADR-0043**.
  The substrate the mechanism will consume (probes, failure
  records, repo fingerprint, JCS canonical hashing, event trace)
  is production-live.
- **LeWM 23-dim behavioral-vector drift detection** (Memory
  Discipline spec Â§Self-Adjustment Mechanisms item 4,
  v0.6-backlog line 72; also referenced as an emit field in
  Â§Operational Metrics) is **not shipped in v0.5.1**. No
  `src/ract/observability/` package; no `lewm.py`, `drift.py`, or
  `spc.py`; no SPC statistics harness; no drift-alert path. Zero
  source hits for `lewm` / `LeWM` / `23-dim`. Deferred to v0.6
  per **ADR-0044**. The substrate (event trace, per-repo capability
  record, per-repo fingerprint, failure-record aggregation) is
  production-live.
- **`verify` / `review` / `commit` / `document` memory-discipline
  functions** (Memory Discipline spec Â§Function contracts;
  v0.5.0 shipped `intake` / `research` / `plan` / `edit`) remain
  deferred per ADR-0036 and ADR-0037. Loop composition today runs
  the four v0.5.0 verbs; the four deferred verbs are v0.6 scope.
- **Language chunkers for Java / Kotlin / C# / C / C++** (Memory
  Discipline spec Â§AST Chunking Rules; spec explicitly defers
  Java / Kotlin / C# / C / C++ to v0.6). v0.5.1 ships **four
  chunkers covering five of the ten spec languages** â€” a `python`
  chunker for Python, a shared `typescript_javascript` chunker for
  TypeScript and JavaScript (grouped per spec Â§AST Chunking Rules
  "TypeScript/JavaScript" bullet), a `rust` chunker for Rust, and
  a `go` chunker for Go. The remaining five languages (Java,
  Kotlin, C#, C, C++) are deferred to v0.6 as roughly four
  additional chunkers (C and C++ grouped per the spec's "C/C++"
  phrasing). SP amendment (module_08): pre-amendment wording
  ("chunkers for Python / TypeScript / Rust / Go â€” four of the
  nine spec languages") mis-omitted JavaScript from the shipped
  list and mis-counted the spec at nine; both fixed in this
  amendment.
- **Bonsai council model-based SUMMARY chunk generation** (Memory
  Discipline spec Â§Chunk Overflow item 2). The AST-deterministic
  SUMMARY body producer ships in v0.5.1 via spec-completeness
  module_05 (`format_chunk(SUMMARY, ...)` returns a real
  deterministic body â€” signature + first-line docstring + control-
  flow region counts + up-to-ten external-call targets â€” instead
  of the pre-pipeline `"summary unavailable"` placeholder). The
  provider hook is preserved as the v0.6 slot for a Bonsai council
  adapter; no shipping caller passes a provider in v0.5.1.
  Deferred to v0.6 per **ADR-0046**.
- **Non-Python AST sub-chunker paths** (TypeScript / Rust / Go).
  Python routes through stdlib `ast` in v0.5.1 via spec-
  completeness module_05; the non-Python languages fall through to
  the blank-line heuristic (`SUB_CHUNK_METHOD_BLANK_LINE` marker
  threaded through `ChunkRow.sub_chunk_method` +
  `Chunk.sub_chunk_method` for observability). Full AST boundary
  support for TS / Rust / Go ships v0.6 alongside the five deferred
  language chunkers. Flagged in ADR-0046.
- **Failure-learning nightly job + human-review queue + retrieval-
  strategy adjustment surface** (Memory Discipline spec
  Â§Failure Learning items 3-5). Aggregation + narrowing-only
  invariant + `apply-narrowings` CLI verb ship v0.5.0 and remain
  operational; the scheduler, the review queue, the reviewer CLI
  surface (list / approve / reject verbs + approval durability
  store per ADR-0045 Â§Flagged gaps), and the retrieval-strategy
  override reader are deferred to v0.6. Originally
  scheduled as module_06 of the v0.5.1 spec-completeness pipeline;
  **module_06 CANCELLED** per Ox Alpha adversarial pipeline review
  2026-08-21 Â§1
  (`_BUILD/ract_v0.5.1_spec_completeness/ox_alpha_reviews/pipeline_challenge_2026-08-21.md`) â€”
  bundling three primitives without an operator workflow was
  identified as the primitive-without-wiring trap pre-committed
  for a point release. Deferred to v0.6 per **ADR-0045**.
- **`index_digest()` equivalence-based no-op-rebuild short-circuit
  on the 3 indexes** (v0.2-primitive salvage item, Lens 2 Delta 4).
  Sub-item of spec-completeness module_07; **CANCELLED** per Ox
  Alpha Â§2 rule ("utility functions with green tests + zero
  production callers are the classic residue of wiring pipelines").
  A named production caller â€” reload cadence that would short-
  circuit on unchanged digest â€” does not exist in the v0.5.1
  retrieve / cache / watcher / composition surface (verified by
  pre-build grep at module_07). Reopens in v0.6 only if a reload
  cadence emerges.

### Known limitations (carried to the v0.6 hardening backlog)

The nine external-review-response modules each queued their own
`## Flagged gaps` roll to v0.6. The load-bearing items:

- **POSIX dir-fsync + one-instance-per-dir enforcement for WAL
  rotation** (module_01). Rotation is atomic within a single instance;
  concurrent-writer safety across `os.replace` boundary defers to v0.6.
- **UTF-16 code-unit sort upgrade for JCS.** RFC 8785 specifies
  UTF-16 code-unit sort; current implementation uses codepoint sort.
  Byte-identical output on the ASCII path; non-BMP disagreement
  surfaces on v0.6 fuzz corpus (module_03).
- **Merkle-of-JCS-lines for JSONL ledgers** (module_03). JSONL ledgers
  hash each line under JCS but no per-line Merkle summary; a v0.6 rot
  audit reads the whole file.
- **HMAC operator key â†’ Ed25519 with revocation ceremony**
  (module_04). Current HMAC-SHA256 matches the stated threat model
  (possession-only); Ed25519 upgrade + revocation flow defer to v0.6.
- **Push-time compensator escalation** (module_05). `check_pushed`
  refuses compensation on pushed commits; the operator-facing
  escalation path (RFC-signed override) defers to v0.6.
- **Env allowlist Merkle attestation** (module_05). Env passthrough
  logged count-only; per-name attestation defers to v0.6.
- **EventChain prev_hash reset on fresh writer** (module_06). A
  freshly-instantiated writer resets the chain-head pointer; the
  pre-existing invariant is exposed by the ambient path but was not
  introduced by v0.5.1.
- **Ledger rotation with roll-forward Merkle tie** (module_07). The
  ledger is single-file append-only; rotation-with-roll-forward-
  hash-tie defers to v0.6.
- **Ed25519-signed ledger appends** (module_07). Current appends
  are covered by the run_id + manifest_digest binding in the signed
  Rootknot canonical bytes; a per-append signature defers to v0.6.
- **Consolidate two Python dead-code detectors** (module_08). Legacy
  `enforce_g5` and new `dead_code_polyglot` both cover Python; a
  single detector routed by extension defers to v0.6.
- **Grammar-version pin ADR** (module_08). Tree-sitter grammars pin
  via `pyproject.toml` version specifiers; an ADR documenting the
  pin policy defers to v0.6.
- **Dense one-liner boundary case** (module_09). Pure single-liner
  function response with no prose lands at floor 1; adding a
  "function body non-empty AND response body non-empty" bump
  defers to v0.6.
- **`retrieval_attestation` run-context binding.** Carried from the
  v0.5.0 CHANGELOG "Known limitations" section. Module_02's
  Rootknot canonical-bytes extension partially closes it (the new
  `run_id` field is now bound into the signed surface); a unified
  payload that folds `prompt_digest` + `workspace_digest` INTO the
  `retrieval_attestation` bundle-hash context defers to v0.6.
- **Regex fallback F1 gate for sycophancy v2** (module_09). The
  regex fallback path lacks its own corpus gate; a "fallback corpus"
  subset that force-flips `used_regex_fallback` to True defers to
  v0.6.

Deferred from the wiring-completion pipeline (see
`_BUILD/ract_v0.5.1_wiring_completion/module_XX.md`):

- **8 doc footers still carry pre-v0.5.1 stamps** (wiring Lens B M3
  residual). Four of twelve older docs were bumped to a v0.5.1
  footer; the rest keep their v0.1.1 / v0.2.0 / v0.4.0-rc1 stamps
  because their content did not change materially. A bulk footer
  refresh defers to v0.6.
- **`index.md` framing** (wiring Lens B M4 residual). The doc index
  CHANGELOG link + footer land at v0.5.1 but the v0.3 framing +
  solo v0.2.0 release-note link remain.
- **`RACT_v0.4.1_INTENT_FIDELITY_SPEC.md` and
  `RACT_v0.5.0_PRE_PUSH_CLEANUP_SPEC.md`** (wiring Lens B M8 OPEN)
  are cited in older CHANGELOG entries but not present under
  `docs/`. Reconstruction defers to v0.6.
- **Manifest-ledger `verify_chain` external anchoring** (wiring
  Lens F H4 SP Q3 PARTIAL residual). The physical-vs-stamped-index
  density check catches naive middle-excise; a full-recompute + a
  correlated tail-truncate + pre-module_09 excise class still
  require external anchoring (Merkle root pinned in a signed
  Rootknot). Documented in `verify_chain` docstring; defers to v0.6.
- **Loop-controller L1/L2/L3 low-severity items** (wiring Lens G
  G-09/G-10/G-11) â€” `OSError` transparency in a specific error
  path, dup-digest short-circuit micro-optimisation, and
  `check_t2` docstring polish. Non-blocking.

Complete Flagged gaps roll per module is preserved in the pipeline
fragments at `_BUILD/ract_v0.5.1_external_review_response/module_0N.md`
and `_BUILD/ract_v0.5.1_wiring_completion/module_0N.md`.

## [0.5.0] - 2026-08-19 â€” Memory Discipline

Minor release for the Memory Discipline pipeline
(`_BUILD/ract_v0.5.0_memory_discipline/`). This release installs a new
memory substrate on top of v0.4.1: a token budget accountant with a
hard ceiling, three query indexes (symbol / graph / semantic), a
four-level retrieve primitive with cascade + query cache, four
function contracts (intake / research / plan / edit), four playbooks
carrying compositions of those functions, three self-adjustment probes
(needle / coherence / adherence) with per-repo capability fingerprint,
and integration wiring into the existing SubstrateLoop and Rootknot
schema. Tag is `v0.5.0`. Nine ADRs (ADR-0031 through ADR-0039) name
the load-bearing decisions.

### Per-module surface

- **module_01 â€” token budget system.** `src/ract/memory/budget.py`
  ships `BudgetAccountant` + `BudgetDeclaration` with hard-ceiling
  refusal, composition override, and runtime narrowing;
  `budget_defaults.yaml` defines defaults for the four v0.5.0
  functions; ADR-0031 names the ceiling policy.
- **module_02 â€” symbol index.** `src/ract/memory/symbol_index.py` with
  SQLite schema at `symbol_index_schema.sql`, tree-sitter parsers for
  Python / TypeScript / Rust / Go under `memory/languages/`, and an
  incremental file watcher at `watcher.py`; ADR-0032.
- **module_03 â€” graph index.** `graph_index.py` with SQLite edge
  schema, `multilspy` LSP client at `lsp.py`, `lsp_fallback.py` for
  when a language server is not installed, and a query API covering
  callers / callees / blast_radius / path / orphans / hotspots;
  ADR-0033.
- **module_04 â€” semantic index.** `semantic_index.py` backed by a
  LanceDB store at `.rack/index/semantic/`, `bge-small-en-v1.5` as the
  default embedding, and a token-bounded search API; ADR-0034.
- **module_05 â€” retrieve primitive.** `retrieve.py` with a four-level
  cascade (symbol â†’ graph â†’ semantic â†’ best-effort), `cache.py`
  keyed on `(query_hash, repo_commit_hash)`, `chunk.py` formatter with
  four formats (FULL / BODY_ONLY / SIGNATURE / SUMMARY), and
  `query_trace.py` for observability; ADR-0035.
- **module_06 â€” function contracts.** `memory/functions/` package
  ships `intake.py`, `research.py`, `plan.py`, `edit.py` with typed
  contracts, prompts under `functions/prompts/`, a mock provider under
  `functions/testing/`, and a session context at `memory/session.py`;
  ADR-0036.
- **module_07 â€” playbook composition.** Four YAML playbooks
  (`refactor_rename`, `refactor_extract`, `bug_fix`, `unit_test`)
  under `memory/playbooks/`, `composition_runner.py` orchestrating
  the four-function stack per playbook step, and `composition.py`
  primitives; ADR-0037.
- **module_08 â€” self-adjustment probes.** Three probes
  (`needle`, `coherence`, `adherence`) under `memory/probes/` with
  `scheduler.py` per-repo dispatch, `failure_records.py` aggregation,
  and `repo_fingerprint.py` for per-repo capability persistence at
  `.rack/probes/capability.json`; ADR-0038.
- **module_09 â€” integration with existing RACT.** Seven new EventKind
  members (`budget.declared`, `budget.exceeded`, `retrieval.requested`,
  `retrieval.satisfied`, `retrieval.cascaded`, `retrieval.refused`,
  `probe.evaluated`) added to `trace/events.py`; `SubstrateLoop`
  reads `SubstrateStepSpec.metadata["retrieval_bundle"]` and emits a
  paired `retrieval.satisfied` event; `Rootknot` generator payload
  gains optional `retrieval_attestation`; ALM `enforce_g6` +
  `enforce_g7` accept `CandidateDiff | None`; `ract memory init`,
  `ract memory apply-narrowings`, and `ract retrieval query` land as
  CLI subverbs; ADR-0039.
- **module_10 â€” release close.** This entry, version triple bump
  0.4.1 â†’ 0.5.0, ROADMAP compilation, combined 56-signal sweep, tag.

### Fixed (memory-discipline)

Fix commits landed in this pipeline (all under
`memory(v0.5)` and identified by short SHA):

- `86583f2` memory(v0.5): fix module_01 auction allowlist for
  pre-wired helpers.
- `5b62a21` memory(v0.5): re-lock golden hash for module_01
  additions.
- `9bc0bb6` memory(v0.5): allowlist module_02 imports in
  public-provenance test.
- `b38a425` memory(v0.5): fix module_02 SP findings Q1+Q2 â€”
  type-alias and let-arrow chunking.
- `ede85a9` memory(v0.5): fix module_03 SP findings Q1+Q3 â€”
  atomicity docstring + probe.
- `d97d50b` memory(v0.5): fix module_04 SP findings Q1+Q3 +
  closed-IP scan.
- `b8bb510` memory(v0.5): fix module_07 SP findings Q2+Q3 + POST
  chains + hash re-lock.
- `72a83d3` memory(v0.5): untrack `_BUILD/` pipeline scratch
  (gitignored per convention).

Modules 04-09 also folded Second-Pass regression tests INTO the
main landing commit (no separate fix commit) per each module's
Second Pass log; the module fragments record the fold decisions.

### Added

- **`src/ract/memory/` package** â€” 30+ Python modules covering budget
  accountant, three indexes, retrieve primitive, four function
  contracts, playbook composition, and three self-adjustment probes.
- **Four playbooks** â€” `refactor_rename.yaml`, `refactor_extract.yaml`,
  `bug_fix.yaml`, `unit_test.yaml` under
  `src/ract/memory/playbooks/`. Eight further playbooks defer to v0.6.
- **Four function prompts** â€” `intake_v1.md`, `research_v1.md`,
  `plan_v1.md`, `edit_v1.md` under
  `src/ract/memory/functions/prompts/` gated by
  `verify_prompt_coverage` at import time.
- **Budget defaults** â€” `src/ract/memory/budget_defaults.yaml` with a
  declaration per v0.5.0 function.
- **Two SQL schemas** â€” `symbol_index_schema.sql` and
  `graph_index_schema.sql`.
- **Seven new event kinds** in `src/ract/trace/events.py::EventKind`:
  `budget.declared`, `budget.exceeded`, `retrieval.requested`,
  `retrieval.satisfied`, `retrieval.cascaded`, `retrieval.refused`,
  `probe.evaluated`.
- **Nine ADRs** â€” ADR-0031 through ADR-0039 under `docs/ADRs/`.
- **Three CLI subverbs** â€” `ract memory init`,
  `ract memory apply-narrowings`, `ract retrieval query` (skeleton;
  full three-index wiring queued for v0.6 polish).
- **`docs/ARCHITECTURE.md`** â€” nine new sections describing each
  memory-discipline surface.
- **`docs/EVENTS.md`** â€” schema_version bumped 2 â†’ 3 with the seven
  new kinds documented.
- **`tests/memory/`** â€” 450+ new tests across the memory-discipline
  surface; five new tests under `tests/contracts/` +
  `tests/test_release_surface.py` covering the integration wiring.

### Extended

- **`SubstrateLoop.run_step`** reads
  `SubstrateStepSpec.metadata["retrieval_bundle"]` when present and
  emits `retrieval.satisfied` per step. Absent metadata is a no-op;
  existing callers do not need to change.
- **`Rootknot` generator payload** gains an optional
  `retrieval_attestation` field; older sidecars continue to verify
  under the v2 compatibility reader path. No signature added, no
  schema-version bump.
- **ALM `enforce_g6_edit` and `enforce_g7_edit`** land as edit-path
  gate helpers.
  `enforce_g6_edit(diff: CandidateDiff | None, plan, *, step_id=None)`
  raises `LazinessViolatedError(kind="diff_without_plan")` when
  `diff is None`, so a caller cannot silently bypass the under-edit
  closure gate; legacy callers reach `enforce_g6(transaction, graph,
  edited_symbols)` instead.
  `enforce_g7_edit(diff: CandidateDiff, companion, *, step_id=None)`
  requires a non-Optional `CandidateDiff` and raises
  `LazinessViolatedError(kind="companion_flagged")` when the companion
  provider rejects the review.
  Path normalization at `_normalize_file_path` closes the
  backslash / leading-dot-slash Second-Pass finding.
- **`ract` CLI** learns `memory` and `retrieval` subverbs via the
  existing dispatch layer; existing verbs untouched.
- **`docs/ARCHITECTURE.md`** gains nine new sections; every ADR-0031
  through ADR-0039 named in the ADR comment lines.

### Verified

- **56-signal sweep.** 11 REBUILD + 16 SUBSTRATE + 16 ALM + 13 new
  MEMORY signals all evaluate true at the tag commit via
  `pytest -q tests/test_release_surface.py`.
- **Per-module attestations.** Nine memory-discipline modules each
  ship a Second Pass log + POST-audit chains + Flagged gaps section.
  Test gate: `test_roadmap_carries_memory_discipline_module_gaps`.
- **Sacred spine tests.** Rootknot three-signature schema unchanged;
  `__root_author__` audit still refuses re-entry; AL-1 property tests
  green.
- **Closed-IP wordlist scan.** 25 terms; zero hits outside the two
  documented `assets/demo.cast` deferrals. Test gate:
  `test_no_closed_ip_terms_in_tracked_files`.
- **Version triple.** `VERSION`, `pyproject.toml [project].version`,
  and `src/ract/__init__.py __version__` all equal `0.5.0`;
  `ract --version` prints `RACT 0.5.0`. Test gates:
  `test_version_matches_across_files` and
  `test_ract_version_cli_reports_aligned_identity`.
- **Golden hash re-locked** at fixed-point after every landing +
  Second Pass fold; locked value at tag:
  `2905a2b789aa9900398de7ce6924d32919dd532618a835c118841c8c3826b8b0`.
- **Baseline pre-existing failures from v0.4.1 remain fixed** at the
  v0.5.0 tag (four failures triaged and closed at v0.4.1 release
  close; verified green here).

### Known limitations (carried to the v0.6 hardening backlog)

Module_09 explicitly deferred 19+ inbound integration constraints
from modules 01-08 POST chains to v0.6, on the judgment that
module_09 ships the integration *shape* while v0.6 ships the
*polish*. The load-bearing deferrals are:

- **`retrieval_attestation` run-context binding (deferred to v0.5.1).**
  The new `retrieval_attestation` field on the Rootknot generator
  payload binds the retrieval bundle bytes but not the surrounding
  run context. A valid signed knot can carry a byte-authentic bundle
  attestation unbound to the `run_id`, `prompt_hash`, or
  `workspace_snapshot_digest` under which it was produced, so a bundle
  can be replayed into a different run context. Same replay-attack
  vector the DeepSeek REVIEW_2 external-review pass identified during
  Memory Discipline Rootknot review; the new field arrives with the
  weakness rather than the fix. Unified-payload extension
  (`run_id` + `prompt_hash` + `workspace_snapshot_digest` folded into
  the signed surface) is queued as a v0.5.1 blocker.
- **Three-index CLI query wiring.** `ract retrieval query` lands as a
  CLI skeleton; the actual retrieve primitive is invoked programmatically
  from `SubstrateLoop`. Wiring the CLI subverb to the three indexes
  end-to-end defers to v0.6.
- **Provider bridge for MemoryFunctionProvider.** The four function
  contracts are called via a mock provider in tests; wiring the real
  provider adapter to production `LlmProvider` defers to v0.6.
- **SUMMARY chunk-format provider adapter.** Retrieve emits
  SUMMARY-format placeholder text; a real summarization provider
  hook defers to v0.6 (module_05 gap #2 / module_06 gap #9).
- **`verify_prompt_coverage` startup wiring.** The gate runs at
  import time inside `prompts_loader`; wiring it to a startup-time
  RACT invocation check defers to v0.6.
- **`probe_lancedb` startup probe.** LanceDB availability check runs
  on first index touch; a startup-time probe defers to v0.6.
- **`current_budgets` from probes.** Probes emit
  `probe.evaluated` events; feeding probe outcomes back into
  `current_budgets` per function defers to v0.6.
- **`PhaseRecord` token counts.** PhaseRecord carries an outcome but
  not the token counts consumed by each phase; wiring the estimator
  to write token counts per phase defers to v0.6
  (module_08 gap #4).
- **Wall-clock `update_file` guard.** Retrieve's update_file path is
  guarded by a call-count budget, not a wall-clock budget
  (module_05 gap #4).
- **LSP language dispatch.** `composition_runner._run_edit_single`
  groups by file path; the LSP dispatch per language defers to
  v0.6 (module_07 gap #1).
- **`composition_runner` as `ract run`.** Composition is exposed
  programmatically; wiring it as the default runner behind
  `ract run` defers to v0.6.
- **Playbook budget overrides.** Playbooks parse `retrieval_overrides`
  at YAML load; forwarding full `RetrievalQuery` shape defers to v0.6
  (module_07 gap #4).
- **`plan.mid_invocation_queries`.** Plan phase queues mid-invocation
  retrieval queries; the runner does not yet re-run retrieve on each
  such query (module_07 gap #4 pair).
- **Noise-tolerant needle reducer** (module_08 gap #1).
- **`mkstemp` tmp-file leak on SIGKILL** in atomic-replace paths
  (module_08 gap #2).
- **Fallback-reference inflation** in adherence probe when the
  operator's rejected proposal itself references a fallback
  (module_08 gap #3).
- **Coherence-probe semantic-diff** â€” probe compares hashes not
  semantic overlap (module_08 gap #5).
- **Adherence-probe placement variants** â€” probe accepts the operator's
  proposal at any position (module_08 gap #6).
- **Fingerprint git-log purity** â€” probe reads git log fields that are
  not strictly deterministic under concurrent commits (module_08 gap #7).
- **Second-Pass prompt-must-inline-source convention.** Module_08 SP
  first attempted a description-only prompt and got fully hallucinated
  verdicts. The convention is now: inline the source bundle in every
  SP prompt for release-surface changes. Documented as inbound
  constraint to module_09 pipeline dispatch (module_08 gap #8).

All items compiled into `docs/ROADMAP.md` under
`## v0.6 hardening (from memory-discipline module_0N)` sections
per module.

## [0.4.1] - 2026-08-17 â€” Intent-Fidelity

Patch release for the Intent-Fidelity pipeline
(`_BUILD/ract_v0.4.1_intent_fidelity/`, patch-versioned per semver since
the pipeline delivered drift-audit and fix commits only, no new features
and no breaking changes). This release verifies that seven prior eras' stated
intents still hold as actual behavior of the current tree and lands fix
commits for drift the audits found. Tag is `v0.4.1`.

### Verified (intent-fidelity by era)

- **v0.1.x era (module_01).** Nine intent statements: 6 PERSISTS, 2 PARTIAL,
  1 DRIFTED. Trust and tooling surface (dead-code auction, Fence,
  consolidation pass, rot report, provider routing) audited against the
  current tree; drift closed with fix commits. See
  `_BUILD/ract_v0.4.1_intent_fidelity/module_01.md` for the per-statement
  verdict rollup.
- **v0.2.0 REBUILD era (module_02).** Nine intent statements: 7 PERSISTS,
  2 PARTIAL. Signed Rootknot origin, RK-1 and RK-2 invariants, assumption
  registry, T1-T7, threat model, versioned plan schema, eval harness first
  cut audited. Both PARTIAL verdicts routed to ROADMAP with substrate-era
  owners.
- **v0.3.0 REBUILD era (module_03).** Ten intent statements: 10 PERSISTS.
  Auditability and depth surface (`PROVENANCE.md`, independence lint,
  benchmark harness, `SessionKey.rotate`, provenance verify CLI, executor
  wiring) audited clean; two fix commits landed for module_02 carry-forward
  gaps.
- **v0.4.0 SUBSTRATE era (module_04).** Sixteen Â§11 signals: 12 PERSISTS,
  4 PARTIAL (signals 4, 5, 9, 10 sharing one architectural root cause: the
  executor-adapter shim constructs SubstrateLoop without manifest /
  sandbox_backend / event writer). One fix commit landed for the v0.3
  provenance-verify silent-partial gap.
- **v0.4.0 ALM era (module_05).** Sixteen Â§13 signals: 6 PERSISTS, 10
  PARTIAL. All ten PARTIAL share the same architectural root cause as
  SUBSTRATE 4/5/9/10 (no runtime path plumbs run_id + workspace-root
  through the loop). One fix commit extended the AL-1 property test to
  enumerate all three sub-clauses independently.
- **v0.4.0-rc1 audits era (module_06).** Six intent statements: 5
  PERSISTS, 1 PARTIAL note-only (CHANGELOG retag-addendum cite stale by 11
  commits; tag body itself clean). One fix commit generalized two residual
  filename references and pinned a wordlist regression gate at
  `tests/test_release_surface.py::test_no_closed_ip_terms_in_tracked_files`.
- **Restoration clusters 1 + 2 era (module_07).** Eleven intent statements:
  10 PERSISTS, 1 PARTIAL note-only (primitive lands with 4 green tests but
  zero consumers; a genuine None-vs-unpassed ambiguity is required at a
  callsite before adoption is warranted). Zero fix commits â€” all persistence
  paths are behavior-gated and hold.

### Fixed (intent-fidelity)

Ten fix commits landed in this pipeline under `intent-fidelity(v0.5): fix`:

- `755578f` intent-fidelity(v0.5): fix â€” merge-gate `_score` reads current
  value not delta (module_01).
- `f4598ed` intent-fidelity(v0.5): fix â€” restore `ract manifest` alias for
  `repro-manifest` (module_01).
- `ceeef12` intent-fidelity(v0.5): source-tree golden hash re-lock after
  fix commits (module_01).
- `84ece29` intent-fidelity(v0.5): fix â€” `ai-sbom` accepts current-shape
  `Receipt` (module_03, closing module_02 punt gap).
- `fdd7474` intent-fidelity(v0.5): fix â€” `PROVENANCE.md` names v0.4
  extended attestations (module_03).
- `9e56078` intent-fidelity(v0.5): source-tree golden hash re-lock after
  module_03 fix commits.
- `881c5ee` intent-fidelity(v0.5): fix â€” `provenance verify` names unset
  v2/v3 extended fields (module_04, closing module_03 gap 2).
- `b6cc908` intent-fidelity(v0.5): source-tree golden hash re-lock after
  module_04 fix.
- `bfecde4` intent-fidelity(v0.5): fix â€” AL-1 property test enumerates all
  three sub-clauses independently (module_05).
- `9e6d0f9` intent-fidelity(v0.5): fix â€” generalize residual dispatcher-name
  filename references plus pin wordlist regression gate (module_06).

Plus, at module_08 release close:

- `intent-fidelity(v0.5): fix` â€” carried-forward gaps + pre-existing test
  failures (QUICKSTART template scrub, `plan analyze` vs. spec `plan risk`
  naming drift, CHANGELOG retag-addendum cite refresh, four pre-existing
  test failures triaged: two G7/G8 date-drift fixtures refreshed, one
  dead-code allowlist entry for `sentinels.py`, one README `evals/README.md`
  reference).
- `release(v0.5.0)` â€” initial release-close commit: VERSION triple bump,
  release-surface test refresh, initial `[0.5.0]` CHANGELOG entry, README
  refresh, ROADMAP compiled from every era. Version was corrected to
  `0.4.1` by the pivot commit below per semver (drift-audit plus fix
  commits, no new features and no breaking changes â†’ patch, not minor).
- `release(v0.4.1)` â€” semver pivot: VERSION triple `0.5.0` â†’ `0.4.1`,
  CHANGELOG heading `[0.5.0]` â†’ `[0.4.1]`, ROADMAP labels
  `v0.6 hardening` â†’ `v0.5 hardening`, tag `v0.5.0` retagged as
  `v0.4.1` on the pivot commit.

### Verify

- 43-signal sweep: 11 REBUILD + 16 SUBSTRATE + 16 ALM. Every signal
  evaluates true at the tag commit via
  `pytest -q tests/test_release_surface.py`.
- Per-module intent-fidelity attestations: seven modules, one
  `## Intent verification results` section per module fragment. Test
  gate: `test_intent_fidelity_module_attestations_logged`.
- Closed-IP wordlist scan: 25 terms, zero hits outside the two documented
  deferrals in `assets/demo.cast`. Test gate:
  `test_no_closed_ip_terms_in_tracked_files`.
- Version triple: `VERSION`, `pyproject.toml [project].version`, and
  `src/ract/__init__.py __version__` all equal `0.4.1`; `ract --version`
  prints `RACT 0.4.1`. Test gate: `test_version_matches_across_files` and
  `test_ract_version_cli_reports_aligned_identity`.

### Known limitations (carried to the v0.5 hardening backlog)

- **Ten ALM PARTIAL signals share one shim-wiring root cause.** ALM signals
  1-10 plus signal 16 (module_05) and SUBSTRATE signals 4, 5, 9, 10
  (module_04) all lack the same architectural piece: the executor-adapter
  shim constructs `SubstrateLoop` without a `CapabilityManifest`, a
  `SandboxBackend`, or a `JsonlEventWriter`, so no runtime path plumbs
  `run_id` + workspace-root through the loop and the ten anti-lazy report
  files never land under `evals/runs/<run_id>/`. Fixture-only coverage
  holds; the runtime side is v0.5 hardening scope (see
  `docs/ROADMAP.md::v0.5 hardening (from substrate close)` and
  `::v0.5 hardening (from intent-fidelity module_04/05)`).
- **`sentinels.py` primitive holds without a consumer callsite** (module_07
  statement 5 PARTIAL). The `MISSING` sentinel is production-ready but no
  current API surface has the None-vs-unpassed ambiguity that motivates
  adoption. Consumer-site migration is v0.5 scope, gated on new-surface
  need.
- **11 Flagged gaps carried forward from intent-fidelity modules 01-07.**
  See `docs/ROADMAP.md` v0.5 hardening sections.

## [0.4.0] - 2026-07-26 â€” Substrate + Anti-Lazy (v0.4.0-rc1)

Combined release close for the SUBSTRATE pipeline (`_BUILD/ract_v0.4.0_substrate/`)
and the Anti-Lazy Module (ALM) pipeline (`_BUILD/ract_v0.4.0_antilazy/`). Tag is
`v0.4.0-rc1`; the `rc1` suffix reflects that the ALM code is new and the combined
release surface warrants a candidate cycle before the `v0.4.0` final tag. Every
new CLI verb, every new invariant, every new event kind, and every new config
option added by either pipeline appears in the bullets below.

### Added (substrate)

- **AcceptanceSuite + IntentCompiler + T1 rewrite (module_01, ADR-0010).**
  `AcceptanceSuite`, `AcceptancePredicate`, and `IntentCompiler.compile` land in
  `src/ract/core/`. Every run commits `evals/runs/<run_id>/suite.json`. Loop
  termination T1 reads: all required predicates evaluate true against the final
  snapshot. `LoopState` refuses zero-required-predicate suites.
- **Worktree-per-step transactional execution (module_02, ADR-0011).**
  `StepTransaction` + `TransactionOutcome` in `ract.core.transaction`;
  `WorktreeManager` in `ract.executor.worktree`; `SubstrateLoop` in
  `ract.executor.loop`. `HandshakeRegistry.blocks_commit` blocks dependent
  commits at the git layer. New CLI verbs: `ract session ls`,
  `ract session diff <step_id>`.
- **Capability manifest + OS-enforced sandbox (module_03, ADR-0012 + ADR-0013).**
  `CapabilityManifest` + `ManifestValidator` + `ManifestDigest` in
  `src/ract/security/manifest.py` (Pydantic v2 promoted to a runtime
  dependency). `LinuxSandbox` (Bubblewrap + Landlock + seccomp-bpf) +
  `MacosSandbox` (Seatbelt / sandbox-exec) + `SandboxBackend` protocol.
  `StepTransaction` accepts a `manifest` and carries `manifest_digest`.
  `--yolo` semantics changed to "auto-widen within pre-declared bounds"
  gated on `HandshakeRegistry.widen_manifest_for`. New adversarial
  `tests/security/` corpus.
- **Typed action union + conformance corpus + provider gate (module_04,
  ADR-0014).** Closed 8-kind `Action` discriminated union in
  `src/ract/core/actions.py` with path-traversal guards and `extra="forbid"`.
  Three schema converters in `src/ract/providers/schema.py`
  (`to_openai_structured_outputs`, `to_anthropic_tool_use`,
  `to_json_schema_fallback`). `ResponseValidator` with two-strike halt
  hooked to `TerminationCause.PROVIDER_TIMEOUT`. `evals/conformance/`
  (68 fixtures: schema_compliance + tool_discipline + refusal_fidelity).
  New CLI verb: `ract conformance run --provider <name>`. Router gates
  registration on a passing recent conformance report.
- **Event trace: hash-chained log + OTel export + trace CLI (module_05,
  ADR-0015).** Closed 24-kind `EventKind` vocabulary +
  hash-chained `EventChain` in `ract.trace.events`. `JsonlEventWriter` at
  `evals/runs/<run_id>/events.jsonl`. `OtlpExporter` mirrors events as
  OpenTelemetry spans per GenAI Semantic Conventions. New CLI verbs:
  `ract trace replay`, `ract trace fork`, `ract trace diff`,
  `ract trace to-test`. `docs/EVENTS.md` published (`schema_version: "1"`,
  later bumped to `"2"` in module_06 to add `auction.proposal`).
  `RunReporter` becomes a projection over the event stream.
- **Rootknot re-oriented to environment attestation (module_06, ADR-0016).**
  `Rootknot` extended with `environment_signature`, `acceptance_suite_digest`,
  `predicate_results`, `manifest_digest`, and `schema_version`. **Invariant
  RK-3 (Environmental Attestation)** landed in `verify_workspace` with
  four sub-clauses. Sidecar reader dispatches on `schema`: `sidecar/v1`
  verifies under RK-1 + RK-2 only (RK-3 skipped with `DeprecationWarning`);
  `sidecar/v2` embeds the raw sandbox pubkey (base64) for offline verify.
  `SandboxKey` in `src/ract/security/keys.py`.
- **Whisperer / Fence / Auction contracts (module_06, ADR-0017).** New
  `src/ract/contracts/` package: `WhispererContract` (pre-plan dialect-brief
  injection with per-snapshot cache), `FenceGate` (pre-delete gate with
  single-use ticket admitted by `open_transaction`; `UnfencedDeleteError`
  is the structural refusal), `AuctionSweep` (between-iteration schedule
  gated by `min_iteration_wall_seconds`). New event kind
  `auction.proposal` added to the closed vocabulary; `docs/EVENTS.md`
  `schema_version` bumped 1 â†’ 2.
- **External eval anchors: Aider Polyglot + SWE-bench Lite + LEADERBOARD
  (module_07, ADR-0018).** 10-problem Aider Polyglot subset
  (`evals/polyglot/subset.json`); 5-instance SWE-bench Lite pin
  (`evals/swe_bench_lite/instances.json`) spanning django, pytest, sympy.
  `evals/LEADERBOARD.md` is the canonical published record;
  `evals/leaderboard/update.py` regenerates it idempotently.
  `.github/workflows/evals-full.yml` nightly workflow gated by
  `RACT_EVAL_ENABLED`.
- **SubstrateLoop-as-CLI-default via executor-adapter shim (module_08
  substrate close, `substrate_loop` config flag).** `src/ract/executor/substrate_adapter.py`
  drives `SubstrateLoop.run_step` per `PlannedStep` from a `Harness.run`
  branch gated on `substrate_loop: true` in `ract.yaml`. Legacy
  `Executor.execute` path preserved for non-git workspaces.

### Added (anti-lazy)

- **Held-out suite (G1) + Mutation-kill (G2) (module_01, ADR-0019).**
  `DualAcceptanceSuite` + AES-GCM-sealed held-out predicates in
  `src/ract/antilazy/holdout.py`. `enforce_g1` / `enforce_g2` pre-commit
  helpers. `MutmutSource` stub. `evals/antilazy/G1-G2/` fixtures. New
  event kind `laziness.violated`. New config: per-intent G2 threshold,
  trivial-rate ceiling (0.3 over last 20 compositions) in module_04.
- **Patch differentiation (G3) + Coverage delta (G4) (module_02, ADR-0020).**
  `src/ract/antilazy/patchdiff.py` (companion-generated differentiator
  suite + AST-normalized leakage fingerprint + `--grep-marker` scan +
  retrieval-index secondary query). `coverage.py` (per-touched-file delta,
  three-run flakiness sample). `enforce_g3` / `enforce_g4` pre-commit
  helpers. `evals/antilazy/G3-G4/` fixtures (null_patch, solution_leakage,
  coverage_stagnation).
- **Test integrity (G5) + Symbol-graph under-edit (G6) (module_03, ADR-0021).**
  `src/ract/antilazy/testintegrity.py` â€” AST diff analyzer denying
  `pytest.skip`, `xfail`, `mark.skip*`, `mark.xfail`, assertion-removal,
  `assert True`, denied-file-edit, monkey-patch, and metaprogramming-escape
  shapes (including `importlib.import_module` and
  `type().__getattribute__`). `symgraph.py` â€” stdlib-ast symbol graph
  with SQLite snapshot-digest cache; `symgraph.db` + `.gitattributes`
  linguist-generated exclusion; `UnderEditReport`. Capability manifest
  extended with a `test_integrity` section (ALM Â§3.5 defaults;
  `ManifestValidator` refuses narrowed `denied_ast_patterns` /
  `denied_file_edits`). `enforce_g5` / `enforce_g6` pre-commit helpers
  emit `laziness.violated` with `kind=test_hack_denied` /
  `under_edit_uncovered_callers`.
- **Companion provider (G7) + Effort reconciliation (G8) (module_04,
  ADR-0022).** `src/ract/antilazy/companion.py` (`CompanionConfig` +
  `CompanionRedTeamReport` + `run_companion` + `enforce_different_provider`
  + `CompanionProviderCollisionError`). `effort.py` (`EffortEstimate` +
  `EffortActual` + `EffortReconciliation` â€” deterministic static
  heuristic with keyword-packing defense + small-fix suppressor +
  greenfield fallback). `completion_gate.py` (`CompanionBundle` +
  `CompletionGateOutcome` + `run_completion_gates`). `LoopController`
  accepts `companion` + `effort_estimate` kwargs; T1 done-callback runs
  completion gates. `evals/conformance/anti_lazy/` (10 fixtures);
  `_score_anti_lazy` scorer; `check_provider_gate anti_lazy_conformance`
  threshold (default 0.7). `evals/conformance/COMPANION_MATRIX.md` +
  `evals/leaderboard/update_companion_matrix.py` (idempotent regenerator).
- **Sycophancy circuit + Investigator + three-signature Rootknot +
  Invariant AL-1 (module_05, ADR-0023) â€” SACRED-SPINE CHANGE.** Rootknot
  schema bumped to `sidecar/v3` adding `antilazy_signature`,
  `gate_results` (tuple of eight `GateResult`), and `reversal_taint`
  (`"clean" | "partial"`). `AlmVerifierKey` in
  `src/ract/security/alm_verifier_key.py`. `Rootknot.attest_antilazy` /
  `verify_antilazy` / `make_rootknot_v3` triple-attester. `verify_workspace`
  extended with **Invariant AL-1 (Anti-Lazy Attestation)** three
  sub-clauses (AL-1.1 signature verifies; AL-1.2 every `GateResult` PASS
  or approved handshake; AL-1.3 `reversal_taint` clean or on operator's
  `accepted_partial_taint_runs` set). `sycophancy.py` (deterministic
  regex + heuristic classifier; `scan_trace` five-turn window;
  `force_evidence_or_restore` via `_RepairIntentSink` Protocol; emits
  `reversal.suspicious` event). `investigator.py` (`InvestigatorReport` +
  `InvestigatorFinding`; top-20 file selection by symbol-graph adjacency
  with lexicographic-earliest padding; emits `investigator.report` and
  `laziness.violated` `kind=investigator_missing`). Two new event kinds:
  `reversal.suspicious`, `investigator.report`.
- **Isomorphic perturbation gate for rule-like intents (module_06,
  ADR-0024).** `src/ract/antilazy/iso_perturb.py` (`RuleLikeDetection`
  with confidence score + word-boundary matched detector;
  `IsomorphicTransformation`; `transform_intent` producing
  `rename_entities` / `swap_syntax` / `permute_examples`;
  `compare_solutions` with AST-normalized digest + reverse-rename +
  string-similarity fallback; `run_iso_perturbation` orchestrator).
  `IntentCompiler.compile_and_detect_rule_like` extension surfacing
  `(suite, rule_like)`. `LoopController.iso_perturb` kwarg. New
  `iso_perturb.json` report per run; new advisory event kinds
  `iso_perturb_rename_degenerate` and `iso_perturb_producer_error`.
- **Anti-Lazy eval corpus + attested pass rate + companion matrix (module_07,
  ADR-0025).** `evals/antilazy/` corpus with 10 adversarial cases drawn
  from documented public incidents (OpenAI SWE-bench Verified audit,
  Palisade chess-hacking, METR reward-hacking taxonomy, Anthropic
  sycophancy research, iso-perturbation spec). `evals/leaderboard/update.py`
  extended with `claimed_pass_rate` + `attested_pass_rate` +
  `attestation_gap` columns; runs with no rootknot file EXCLUDED from
  both numerator and denominator. FakeProvider caveat marker on the
  leaderboard row. New CI workflow `evals-smoke.yml` (PR-tier 7-fixture
  smoke) alongside the nightly `evals-full.yml`.

### Changed

- **`signature` renamed to `generator_signature` on `Rootknot`** (substrate
  module_06). Deprecated `@property` alias emits `DeprecationWarning`
  and is removed in v0.5.
- **`--yolo` semantics changed** (substrate module_03) from "bypass
  handshake" to "auto-widen within pre-declared bounds" gated on
  `HandshakeRegistry.widen_manifest_for`. Tier 3 stays denied at a
  compile-time constant.
- **T1 termination rewritten** (substrate module_01) from milestone
  oracle to a predicate check reading the final snapshot. The old
  `ProgressOracle` becomes a scheduling heuristic only.
- **Rootknot schema bumped to `sidecar/v3`** (ALM module_05) adding
  `antilazy_signature`, `gate_results`, `reversal_taint`. `sidecar/v1`
  and `sidecar/v2` continue to verify at the non-strict floor; `strict=True`
  refuses v1 and v2 outright.
- **`__root_author__` moved to display-only** (substrate module_06) in
  `src/ract/_about.py`, read only by `ract --about`. Audit grep gate
  enforced by `tests/test_root_author_display_only.py`.
- **`evals/LEADERBOARD.md` FakeProvider display marker** (ALM module_07)
  â€” `` `fake` `` renders as `` `fake` (synthetic, mechanism-check only) ``
  in the provider column.

### Deprecated

- **`Rootknot.signature` property alias** â€” emits `DeprecationWarning`;
  removed in v0.5. Consumers migrate to `Rootknot.generator_signature`.
- **`sidecar/v1` and `sidecar/v2`** â€” continue to verify at the non-strict
  floor but skip RK-3 (v1) and AL-1 (v1 + v2) with
  `DeprecationWarning`. `strict=True` refuses them. Re-sign under
  v0.4-ALM to lift the bar.

### Removed

- Unused experimental modules and CLI subcommands from earlier
  development that were not part of the v0.4 substrate design. Users of
  the shipped v0.4 CLI verbs are unaffected.

### Verify

- **`v0.4.0-rc1` naming convention.** Substrate pipeline's plan referred
  to a `v0.4.0` tag, but substrate module_08 deferred the entire release
  surface (CHANGELOG, README, VERSION, ROADMAP, tag) to this pipeline.
  ALM's module_08 lands the FIRST v0.4-family tag as `v0.4.0-rc1` â€” the
  `rc1` suffix reflects that ALM code is new and the combined shape
  warrants a candidate cycle before `v0.4.0`. VERSION carries the
  human-friendly `v0.4.0-rc1`; `pyproject.toml` and `__init__.py` carry
  the PEP 440 canonical `0.4.0rc1`; `ract --version` prints `RACT
  0.4.0rc1` (PEP 440 normalises `0.4.0-rc1` and `0.4.0rc1` to the same
  version identity â€” see `tests/test_release_surface.py`
  `test_version_matches_across_files` and
  `test_ract_version_cli_reports_aligned_identity`). The tag itself
  uses the `v0.4.0-rc1` git convention.
- **46-signal sweep (documented total).** The plan called for a combined
  46-signal sweep (14 REBUILD + 16 SUBSTRATE + 16 ALM). Honest
  enumeration of the three specs finds 11 REBUILD signals (per
  `docs/RACT_v0.3_REBUILD_SPEC.md` Â§4) + 16 SUBSTRATE + 16 ALM = **43
  distinct signals**. `tests/test_release_surface.py` enumerates and
  evaluates all 43; the test formerly named `test_combined_signal_count_46`
  is renamed `test_combined_signal_count_matches_documented_total` and
  asserts 43.
- **New invariants.** RK-1 (Author Attestation, v0.2), RK-2 (Sidecar
  Integrity, v0.2), RK-3 (Environmental Attestation, this release), AL-1
  (Anti-Lazy Attestation, this release).
- **New CLI verbs (substrate).** `ract session ls`,
  `ract session diff <step_id>`, `ract conformance run --provider <name>`,
  `ract trace replay|fork|diff|to-test`.
- **New CLI verbs (ALM).** Anti-lazy gates are pre-commit helpers rather
  than top-level CLI verbs; a run's `evals/runs/<run_id>/` gains
  `mutation_kill.json`, `patch_diff.json`, `coverage_delta.json`,
  `test_integrity.json`, `under_edit.json`, `companion_report.json`,
  `effort_reconciliation.json`, `sycophancy.json`, `investigator.json`,
  and (for rule-like intents) `iso_perturb.json`.
- **New config options.** `substrate_loop: true` in `ract.yaml` (substrate
  module_08); `anti_lazy_conformance` threshold in
  `check_provider_gate` (default 0.7, ALM module_04); `AuctionConfig`
  block; `test_integrity` section in `CapabilityManifest`.
- **Retag addendum (2026-07-27, refreshed 2026-08-17).** The
  `v0.4.0-rc1` tag was first cut on commit `1fd764d` (2026-07-26). Two
  audit sweeps have force-moved the tag since:
  1. **2026-07-27 retroactive endpoints audit** landed two initial
     release-surface fix commits, moving the tag to `8b0a6c5`:
     - `0c853a9` audit(v0.4.0-rc1): fix â€” remove operator-project name
       from shipped docs.
     - `8b0a6c5` audit(v0.4.0-rc1): fix â€” substrate adapter rebinds
       every captured helper (enumerated `_HELPER_ATTRS` set plus
       regression test).
  2. **2026-07-27 through 2026-08-17 content-hygiene + functionality
     audits** landed nine more `audit(v0.4.0-rc1)` fix commits and the
     tag rests today at `dafab9a`. The eleven audit commits past the
     initial `1fd764d` tag position, in chronological order:
     `0c853a9`, `8f8b03f`, `c88ddc9`, `224fd90`, `0eed92d`, `2a11bef`,
     `17a4794`, `2fb5715`, `9b63094`, `3577149`, `dafab9a`. Version
     identity, 43-signal count, and every other release-surface claim
     are unchanged.

### Known limitations (carried to the v0.5 hardening backlog)

- Live-model reruns for the ALM `evals/runs/*_antilazy/` reports are
  FakeProvider mechanism-checks; the informative attested-vs-claimed
  delta requires live providers (queued as the nightly
  `evals-full.yml` workflow gated on `RACT_EVAL_ENABLED`).
- Reviewer-drift across the ALM pipeline: four of eight ALM modules'
  Second Pass reviewers fell back from the plan-named endpoint (see
  `docs/ROADMAP.md` "Operator-side dispatcher gaps").
- Full v0.5 backlog compiled from every module's Flagged gaps and every
  Second Pass deferral: see `docs/ROADMAP.md`.

## [0.3.0] - 2026-07-25 â€” Auditability and Depth

### Added

- **Public provenance statement** â€” `docs/PROVENANCE.md` is the single public document describing what a Rootknot attests, how RACT stays independent of private systems, how to verify a Rootknot, and what happens on violation (T3 `PROVENANCE_FAILURE`).
- **Independence lint** â€” `tests/test_public_provenance.py` AST-scans `src/ract/` and fails the build if any module imports from a root not in the curated allowlist. Adding a third-party dependency is now a conscious, reviewed act.
- **Failure-mode architecture** â€” `docs/ARCHITECTURE.md` gained a "Failure modes and concurrency" section; every named failure maps to a real `TerminationCause` or the `authorize_action` gate.
- **Two new ADRs** â€” [ADR-0008](docs/ADRs/ADR-0008-ract-yaml-versioning.md) (`ract.yaml` schema versioning) and [ADR-0009](docs/ADRs/ADR-0009-mcp-tool-execution-boundaries.md) (MCP/tool-execution boundaries), each with rejected alternatives. The repo now carries 9 ADRs.
- **Benchmark harness** â€” `evals/benchmarks/refactor-token-usage/` compares the milestone-driven loop against a naive fixed-iteration baseline on tokens-to-pass, with a committed `report.md` and a CI `benchmark` job. The contender is strictly better (80% fewer tokens on the refactor task).
- **Rootknot ergonomics** â€” `SessionKey.rotate()` archives the old key (pre-rotation rootknots still verify); `ract provenance verify <path>` CLI verb prints `valid`/`invalid`; the executor optionally signs and indexes every artifact write (SQLite + sidecar) when configured.
- **Repo hygiene** â€” `tests/fixtures/` convention with a hygiene lint test (no tracked root JSON, runtime dirs gitignored); CONTRIBUTING documents branch-protection requirements and repository conventions.

### Changed

- README trimmed to under 500 words; every public claim now references a command or a committed report. Added a "Verify" section.
- CI runs `ruff` over `evals/` and adds the `benchmark` job with report artifact upload.

### Removed

- The `_ROOT_KNOT = object()` sentinel deprecation note is retired â€” the sentinel is fully gone from `src/` and `tests/` (verified by grep).

### Known limitations (carried to the hardening backlog)

- `ract.yaml` schema-version enforcement (ADR-0008) is documented but not yet implemented in `config.py`.
- The benchmark proves the termination mechanism on one deterministic task; a multi-task sweep with varied pass-iteration profiles is queued.
- `ract provenance verify` resolves the generator public key from the local key store (the sidecar stores the key *id*, not the raw pubkey); embedding the raw pubkey in the sidecar is queued.
- Branch protection is documented; applying the GitHub settings is an operator action.

## [0.2.0] - 2026-07-23 â€” Provenance and Invariants

### Added

- **Signed Rootknot provenance** â€” every artifact carries an ed25519-signed `Rootknot` binding it to its plan step, assumption, generator, and parent artifacts. See [ADR-0001](docs/ADRs/ADR-0001-provenance-anchored-artifacts.md).
- **Provenance workspace verifier** â€” `verify_workspace` checks invariants RK-1 and RK-2 before every recursion step. See `src/ract/core/provenance.py`.
- **Assumption registry** â€” four-state lifecycle (`proposed`, `active`, `discharged`, `violated`) with transitive violation propagation. See [ADR-0002](docs/ADRs/ADR-0002-assumption-registry.md).
- **Formal loop termination** â€” recursion halts on T1â€“T7 with a distinct `TerminationCause`. See [ADR-0003](docs/ADRs/ADR-0003-milestone-driven-recursion.md).
- **Threat model** â€” capability tiers T0â€“T3, sandbox gating, and a published refuse-list. See [ADR-0004](docs/ADRs/ADR-0004-tool-execution-threat-model.md) and [ADR-0007](docs/ADRs/ADR-0007-what-ract-refuses.md).
- **Capability-based provider routing** â€” router selects providers by capability hint and health. See [ADR-0005](docs/ADRs/ADR-0005-provider-capability-routing.md).
- **Deferred-approval handshakes** â€” high-risk actions queue for async operator review. See [ADR-0006](docs/ADRs/ADR-0006-deferred-approval-handshakes.md).
- **Versioned plan schema** â€” `src/ract/core/schemas/plan-v1.json` with migration support.
- **Eval harness** â€” three reproducible tasks under `evals/tasks/` with committed run reports in `evals/runs/`.

### Changed

- README rewritten to a concise, technical pitch; author content moved to `AUTHOR.md`.
- CI badge and coverage badge added to README.

### Deprecated

- The `_ROOT_KNOT = object()` sentinel is retained as a legacy fallback through v0.2.0 and will be removed in v0.3.0.

## 0.1.2

### Added

- **Signed receipts and receipt chain**: every run produces a signed receipt; receipts can be chained tamper-evidently and exported.
- **Handshake queue**: operator handshakes queue high-risk items for async review.
- **Dead-code auction**: `ract auction list` identifies unreachable modules; `ract auction html-report` exports HTML reports.
- **AI provenance manifest / SBOM**: `ract ai-sbom` and `ract manifest` build and export AI provenance manifests.
- **Configurable CI policy gate**: `ract policy-gate` evaluates JSON policies against run evidence.
- **Coverage delta**: `ract coverage delta|baseline|status|badge` implements earned-coverage gates.
- **Mutation merge gate**: `ract merge-gate` evaluates natural-language merge policies against mutation metrics.
- **Native internal provider**: route prompts to local scripts via `adapter: internal`.
- **MCP adapter health probe**: verify MCP tool wiring before running loops.
- **Receipt leaderboard**: `ract leaderboard` renders model/plan ranking tables from receipts.
- **Deterministic run fingerprints**: `ract run-fingerprint` fingerprints runs for reproducibility studies.
- **Run report exports**: Markdown, HTML, and JSON run reports for CI artifacts.
- **Quality scorecard JSON export**: archive and compare quality scorecards across runs.
- **Novelty scan fast mode**: `ract novelty scan --fast` finishes in seconds for CI.
- **New CLI verbs**:
  - `ract --version`
  - `ract config validate`
  - `ract provider health`
  - `ract session list`
  - `ract plan diff`
  - `ract init --list-templates`
  - `ract doctor --json`
- **JSON output flags** across the CLI surface:
  - `ract retrieval search --json`
  - `ract diff apply --json`
  - `ract skills list --json` and `ract skills marketplace list --json`
  - `ract mcp list --json`
  - `ract run-fingerprint --json`
  - `ract leaderboard --json`
  - `ract mutation run --json`
  - `ract refactor --dry-run --json`
  - `ract whisper --json`
- **Diff applier context verification**: `ract diff apply` now validates hunk context before writing and parses both git-style and plain unified-diff headers.

### Changed

- Thermal governance in the build loop now uses a hard ceiling and a separate concurrency-fallback threshold.
- Provider router now registers the `internal` adapter by default.

## 0.1.1

- Trust and tooling release: dead-code auction, Chesterton's Fence, consolidation, rot report, and provider routing.

## 0.1.0

- Initial public release of RACT.
