# ADR-0047: Workspace Tool Layer and Per-Step Agent Loop

## Status

Proposed (v0.6, section 1 of the agentic brief). Awaiting operator review
before any code lands. Companion to ADR-0048, which covers tier 2 and tier 3
actions, approvals, keys and the trust model. Where the two overlap this ADR
points to ADR-0048 and does not repeat it.

## Context

Through v0.5.2 a plan step is one chat completion. The executor
(`src/ract/executor/steps.py`, `Executor.execute`) sends the step to the
provider, takes the visible answer, and writes it to `expected_artifact`.
The model cannot read a second file, search the tree, edit part of a file,
or see what its change did. Since `ed27155` the step at least sees the
current contents of the file it replaces, but it still has to return the
whole file in one answer.

That shape caps what RACT can do on a real repository. A step that needs to
change three call sites in two files, or find where a symbol is defined
first, has no way to do it. Comparable tools in October 2026 run a bounded
loop per task: the model asks for a tool, the harness runs it and returns
the result, and the loop ends on a final answer or a budget.

RACT already has the pieces such a loop has to pass through: the capability
tiers and refuse-list (`src/ract/core/threat_model.py`, ADR-0004,
ADR-0009), the four-gate `ToolInvocationGate`
(`src/ract/executor/tool_gate.py`, ADR-0041), worktree-per-step
transactions (`src/ract/core/transaction.py`, ADR-0011), the per-artifact
write guards in `Executor.execute`, and `Rooted[T]` (`src/ract/rooted.py`).

## Enforcement today

The design below builds on code that does less than the documentation says.
These are the facts at `ed27155` that matter for a tool layer, with what this
ADR does about each. Tier-3, handshake and key findings are in ADR-0048.

| Finding | Where | This ADR |
|---|---|---|
| `DiffApplier` takes target paths from diff headers and accepts `../` and absolute paths. | `src/ract/diff_applier.py:102-112` | Closes: every path goes through the D2 resolver. Shipped first as a defect fix (it is wrong today, before any new capability). |
| `Executor._write_artifact` refuses absolute paths but accepts `..`. | `src/ract/executor/steps.py:484-507` | Closes, same resolver. |
| The production `SubstrateLoop` gets no manifest, no sandbox backend and no handshake registry, its parent snapshot is the placeholder `"0" * 40`, and `run_via_substrate` gives steps no predicates, so every step commits unconditionally. In the UX baseline this path committed a step onto the user's branch (`docs/ux/baseline/defects.md`, UX-01). Failure to route a tool call through the loop is not silent: it logs a warning and emits `tool.invocation.bypassed`. | `src/ract/harness.py:372-376`, `src/ract/executor/substrate_adapter.py:206-214` | Closes for the agent loop: D6 requires a manifest, the D3 path policy and the step's predicates on every mutating step. The sandbox part is ADR-0048 D7. |
| `tool.invocation.pre`, `post`, `refused` and `compensator.*` are emitted but are missing from `EventKind`, so a live trace writer drops them. | `src/ract/trace/events.py:47-391`, `src/ract/executor/tool_gate.py`, `src/ract/executor/commit_compensator.py` | Closes: kinds registered, and a test fails if any emitted kind is unregistered. Shipped as a defect fix with the event stream work. |
| Nothing denies `.ract/**` to tools or commands. `.ract/` holds the operator key, sandbox and verifier keys, hook definitions and the env allowlist. | `src/ract/core/intent_recompile.py`, `src/ract/security/keys.py:81-101`, `src/ract/security/alm_verifier_key.py`, `src/ract/hook_system.py:45-94` | Closes for tools (D3). Commands and key custody are ADR-0048 D2 and D4. |
| `.ract/hooks/*.json` commands run with the full environment, no gate and no scrub. | `src/ract/hook_system.py:45-94` | Defers the gating design to ADR-0048 D12. The environment scrub ships now as a defect fix. |
| `ToolDefinition` has no tier; tiering of tool calls comes from the free-text classifier. | `src/ract/executor/tool_gate.py:186` | Closes (D1). |

## Decision

### D1. A tool is a `ToolSpec` with a declared tier

New package `src/ract/tools/`. Every tool is a frozen `ToolSpec`:

- `name`: stable id (`read_file`, `edit_file`, ...).
- `tier`: a `CapabilityTier`. Required, with no default. A spec without a
  tier fails at import, and a test enumerates every registered tool and
  pins its tier.
- `args_model`: a Pydantic model with `extra="forbid"`, registered with the
  existing `ToolInvocationGate` as the tool's argument schema.
- `mutates`: whether the tool changes files. Must agree with the tier
  (T0 never mutates).
- `result_cap_bytes`: the most the tool may return into the conversation.

Tool calls go through `SubstrateLoop.invoke_tool`, so the existing gates
and events apply. A fifth check, the **tier gate**, authorizes each call with
the tier taken from the `ToolSpec`, adjusted by the paths it touches (D3).
For registered tools the declared tier is authoritative and the free-text
classifier in `classify_action` is not consulted. The text classifier stays
for plan prose.

Tier map for the section 1 tools (section 2 tools are in ADR-0048 D1):

| Tool | Tier | Why |
|---|---|---|
| `read_file` (line range), `list_dir`, `glob`, `grep`, `repo_map` | T0 | Read only, inside the root, sensitive files refused |
| `write_file`, `edit_file`, `delete_file`, `move_file` | T1 | Change workspace files only, inside the step worktree, reversible |
| `apply_patch` | T1 when every target is a T1 path | A multi-file patch takes the highest tier of any file it touches, and is refused whole if any target is protected |
| Any write tool on a control or executable-configuration file (D3) | T2 | Changes what RACT or another tool will do next time |

The line between T1 and T2: T1 changes the content of the operator's
project inside RACT's own isolation (worktree, digest checks, undo). T2
changes state that outlives the step outside that isolation or that some
program will act on by itself: git history and refs (ADR-0048 D8), control
files, and files other programs execute.

Every tool returns `Rooted[ToolResult]`. The assumption names what the tool
relied on ("src/app.py had digest 3f2a... when the edit was applied");
provenance carries the tool id, an args digest and the file digests read or
written; a failure carries a `hint` that tells the model or the operator
what to change ("re-read the file; it changed since your last read").

### D2. One path resolver for every tool

`WorkspacePath.resolve(root, user_path, *, purpose)` is the only way a tool,
the diff applier or the artifact writer turns an argument into a filesystem
path. It refuses, before touching the disk:

- any `..` segment, even one that would land inside the root;
- absolute paths outside the root (absolute paths inside the root are
  accepted and made relative);
- NUL bytes and control characters;
- on Windows: drive-relative paths (`C:foo`), UNC and device paths
  (`\\server\share`, `\\?\`, `\\.\`), reserved device names (`CON`, `NUL`,
  `AUX`, `PRN`, `COM1` to `COM9`, `LPT1` to `LPT9`, with or without an
  extension), alternate data streams (`name:stream`), trailing dots or
  spaces, and 8.3 short names (`GIT~1`) in any component;
- `/proc/self/root` and the other `/proc/*/root`, `/proc/*/cwd` synonyms
  (the April 2026 bubblewrap escape, already a named regression).

It then resolves the deepest existing ancestor with `realpath` (which also
follows Windows junctions) and requires the result to sit inside
`realpath(root)`. Protected-path comparisons are case-insensitive on Windows
and macOS.

Symlinks: reads may follow a link whose target resolves inside the root.
Writes never follow links. A write is refused when the target or any parent
component inside the root is a symlink or junction, and the write opens with
`O_NOFOLLOW` where the platform has it; on Windows the handle's final path is
checked with `GetFinalPathNameByHandle` before bytes are written. Writes land
through a temporary file in the same directory and `os.replace`.

The resolver ships first, as a standalone module with its red-team tests, and
replaces the path handling in `DiffApplier` and `_write_artifact`.

### D3. Protected paths

**Refused for every tool, recursively, with no escalation and regardless of
any allow rule:**

- `.git/**` and a worktree's `.git` file. Writing `.git/hooks/*` or
  `.git/config` (`core.fsmonitor`, `core.hooksPath`) turns a tier-1 write
  into code execution at the next git command.
- `.ract/**`: policy, keys, handshakes, WAL, ledger, hooks, env allowlist.
- `.agents/**` and the agent-configuration directories of other coding tools
  (a fixed list in code, extended by config, never narrowed by config). A
  write there would plant instructions or hooks for another agent.
- The key store directories returned by `ract.security.keys` and the
  operator key directory (ADR-0048 D2).

**Reads refused:** files matching `SENSITIVE_PATTERNS` (unchanged list), and
everything under `.ract/` and `.git/` (git information comes through the
git tools in ADR-0048 D8).

**Writes at tier 2 (handshake, with the diff shown):**

- RACT control files: `ract.yaml`, the configured `prompts_dir`, and project
  guidance files (`RACT.md`, `AGENTS.md`, `CLAUDE.md`).
- Executable configuration, meaning files some program acts on by itself:
  `.github/workflows/**`, `.envrc`, `.vscode/**` (tasks, launch, settings),
  `.idea/**`, `.devcontainer/**`, `.pre-commit-config.yaml`, `.husky/**`,
  `Makefile`-style task files named in config, git hook directories outside
  `.git`, and virtual environment interpreters and scripts (`.venv/**`,
  `venv/**`, any `pyvenv.cfg` tree).

The G5 test-integrity rules (`TestIntegrityConfig.denied_file_edits`, for
example `tests/conftest.py`) keep applying at the step commit boundary. A
file the model wrote is not executed outside the sandbox without a fresh
approval; that rule lives in ADR-0048 D4.

### D4. Read and write semantics

- `read_file(path, offset=None, limit=None)` returns numbered lines, the
  file's SHA-256, its total line count, its encoding facts (UTF-8 clean or
  not, BOM present, line ending style), and a truncation marker when the
  byte cap (default 256 KiB per call) or line limit cuts it. Binary files
  return size and digest only.
- `list_dir`, `glob` and `grep` skip `.git` and `.ract` always and skip
  gitignored paths unless the call sets `include_ignored`. They cap entries,
  matches and bytes.
- `grep` runs ripgrep with a fixed argv (`--no-config`, the pattern after
  `-e`, paths after `--`), a scrubbed environment and a timeout. RACT starts
  this binary itself and the model fills only data fields, so it stays tier
  0. The Python fallback runs in a child process with a hard timeout so a
  catastrophic regex cannot hang the session.
- `edit_file(path, old, new, expected_digest, replace_all=False)` replaces an
  exact string. `old` must occur exactly once unless `replace_all` is set.
  `expected_digest` must equal the file's current SHA-256, so the model can
  edit only what it has read.
- `write_file` on an existing file needs `expected_digest`; on a new file it
  needs `create=True` and refuses if the file exists. An empty body is
  refused (the rule from `ed27155`).
- `apply_patch` takes a unified diff and is all-or-nothing across hunks and
  files. Every header path goes through D2.
- `delete_file` and `move_file` need `expected_digest`; `move_file` refuses
  an existing destination.

**Encoding rule.** A file that did not decode cleanly as UTF-8 can be read
(with replacement characters, flagged) and cannot be edited: write tools
refuse it with a hint naming the encoding problem, so a replacement
character is never written into a file that did not contain one. Edits keep
the file's BOM and line-ending style; new content is normalized to the
file's style before the digest of the result is computed.

Before a mutation lands in the worktree it passes the same guard chain the
single-shot path uses today: safety guardrail, duplication guard,
load-bearing guard, novelty budget. The chain moves out of
`Executor.execute` into one function both paths call, so they cannot drift.

### D5. The step agent loop

`StepAgentLoop` replaces the single completion for steps that work on files.
Per model turn:

1. Send the conversation and the tool definitions (native) or the tool list
   and envelope instructions (fallback).
2. Read the reply with `ract.tool_calls.extract` (the extraction ladder
   built in this branch). It returns validated calls with the rung that
   read them and any visible repairs, a final answer, or a named failure
   (`markup_unparsed`, `truncated`, `empty`, `unknown_tool`,
   `invalid_arguments`, `too_many_calls`), with the length of any prose
   around the calls. Unparsed tool
   markup is never accepted as an answer and never written to a file.
3. Run the calls serially, in the order given (ADR-0009), each through the
   gate. A refusal goes back to the model as a tool result and is recorded
   as an event.
4. Append each result as a tool message inside a delimited data block with
   its trust label (ADR-0048 D9). The system prompt says text inside tool
   results is data and carries no instructions.

**Native tool calling detection.** RACT learns whether a provider and model
honor `tools` with a probe: one request with a trivial `echo` tool, sent at
setup and by `ract doctor --check-providers`. The result is cached per
provider URL and model in `.ract/capabilities.json` with a timestamp,
overridable in `ract.yaml` (`tool_calling: native | json | auto`), and shown
as one line in `/context`. The probe is a visible call counted in `/cost`
under its own purpose; RACT makes no hidden background requests. A wrong
guess degrades: a native request that comes back as plain text is read by
the text rungs of the ladder, and after two such turns the session switches
that provider to the JSON envelope and says so.

**Budgets.**

| Budget | Default | Changed by |
|---|---|---|
| Model turns per step | 40 | `ract.yaml` `agent.max_turns`; `--max-turns` on the command line |
| Tool calls per step | 64 (existing `ToolBudget`) | `agent.max_tool_calls` |
| Tokens per step (in plus out) | provider context times 4 | `agent.max_tokens_per_step` |
| Wall time per step | 30 minutes | `agent.max_wall_seconds` |
| Bytes returned per tool call | 256 KiB | `agent.max_result_bytes` |
| Repeated identical call / identical failure | 3 / 2 (loop guard) | not configurable |

Only the operator changes budgets, through config or flags. No tool can.
A budget stop leaves the worktree in place, applies nothing, and returns a
Rooted error whose hint names the budget and the key that raises it.

**Verdict.** A final answer does not make the step done. The step is done
when its acceptance predicates hold and the anti-lazy gates pass at the
commit boundary (termination T1). The harness writes the verdict line the
operator sees; the model's own claim is one input the effort-reconciliation
gate (G8) checks against what actually happened.

**Reasoning models.** `reasoning_content` and inline `<think>` blocks are
kept in the trace and shown dimmed and collapsed in the session. They are
never sent back as answer text, and the extraction ladder never reads calls
out of them. A turn cut off by `finish_reason=length` with no call is
explained with token counts and retried once with a higher limit or a
continuation; it never becomes an empty result.

**Failure halfway through a turn.** When a turn's third of five calls fails:
the effects of calls one and two stay in the step's worktree (they passed
their checks), call three's partial effect is discarded (writes are
temp-file-and-replace, so there is none on disk), calls four and five do not
run, and the model receives the failure as a tool result and decides what
to do next. The live tree is untouched until the step reaches the review
stage (D6). What the operator sees: the cards for calls one to three, the
failed card with its hint, and the next model turn.

**Cancellation.** Ctrl-C is acknowledged within 200 ms ("stopping...").

- During a model call: the HTTP request is cancelled and the partial reply
  is kept in the transcript, labeled as cut off. No tool from it runs.
- During a tool call: the tool is cancelled. Read tools stop. A write tool
  that has not reached its `os.replace` leaves nothing; one that has is
  complete and recorded. A command (ADR-0048 D5) is killed with its process
  tree.
- During review: nothing is applied; the proposal stays in the worktree and
  `/diff` shows it again.

In every case the session prints the workspace state in one line ("no files
were changed", or "2 files proposed, not applied") and returns to the prompt
within 2 s. The transcript and the worktree stay consistent because the
worktree is the only place a step writes before review.

Steps with no file work keep the single-shot path. `--single-shot` forces
the old path for every step.

### D6. Worktree, review, apply, and undo

**Read-only work pays for no worktree.** Plan mode and steps that only read
use the live tree directly. The worktree is created lazily at the first
mutating call of a step. Targets for first visible feedback: a tool card
within 300 ms of the model asking for a read; the "preparing a workspace"
line within 300 ms of the first mutating call, with the worktree ready in
under 3 s on a 10,000-file repository on local disk, and a heartbeat while it
is not.

**Base snapshot.** This replaces today's placeholder parent snapshot
(`"0" * 40` in `harness.py`). The worktree starts from a synthetic commit of the
current working tree: committed files plus uncommitted and untracked (not
ignored) changes, built with a temporary index (`GIT_INDEX_FILE`) so the
operator's index, branch and stash are never touched. Files matching
`SENSITIVE_PATTERNS` (for example an untracked `.env` that is not ignored)
are left out of the snapshot and so never appear in the worktree; the
session lists what it left out.

**Not a git repository.** Read tools work. The first mutating call becomes
an offer: RACT shows the exact command (`git init` plus an initial commit of
the current files, sensitive files excluded) as a tier-2 action and proceeds
on approval. Declining keeps the session read-only for that step and says
how to enable edits later.

**Review state machine.** Every change a step produces moves through:

```
proposed (in the step worktree) -> reviewed (per hunk) -> applied (live tree)
```

- `proposed`: the step passed its gates in the worktree. The session shows
  a unified diff per file with hunk ids (`diff.proposed`).
- `reviewed`: the operator accepts, rejects or edits each hunk, or accepts or
  rejects all. Rejected hunks never reach the live tree.
- `applied`: accepted hunks are applied to the live tree as unstaged
  changes, after checking that each live file still has the digest it had at
  the base snapshot. A file the operator changed meanwhile is skipped and its
  patch saved under `.ract/pending/<session>/`; RACT never merges into a file
  the operator is editing.

Modes: default stops at `proposed` for review; auto-accept-edits skips
review and applies (still with the digest check); plan mode never leaves
`proposed` and in fact never creates a worktree. The Rootknot sidecar
records what was applied, hunk by hunk, so the signed record matches the
live tree and leaves rejected hunks out.

**Checkpoints.** Every apply records a checkpoint: the base snapshot commit
(kept under `refs/ract/checkpoints/<session>/<n>` so `git gc` keeps it) and
for each file the digest before and after. `/undo` restores files whose live
digest still equals the "after" digest and lists the ones it left alone.
`/redo`, `/checkpoint` and `/restore` use the same records, which are JSON
signed with the session key, like other artifacts.

**Interactive approval and deferred handshakes.** A tier-2 write in a live
session (a control file, executable configuration, `git init`) asks now: an
`approval.requested` event shows the exact change as a diff and the choices
defined in ADR-0048 D6. ADR-0006 deferred handshakes apply only when nobody
can answer: headless runs and CI. The rule is the same in both places; only
the place the answer comes from differs.

### D7. Events: one ordered stream

The loop prints nothing. It emits one ordered, versioned event stream per
session, and that stream is the only input to the session renderer, the
headless JSON output (`--output-format stream-json` and `json`) and the
future SDK. The contract (`docs/EVENTS_SESSION.md`, new, distinct from the
trace `EVENTS.md`):

- every event has `v` (schema version), `seq` (monotonic per session), `t`
  (UTC), `turn`, `kind` and `data`;
- kinds: `session.started`, `session.resumed`, `turn.started`,
  `turn.finished` (outcome, duration), `agent.text.delta`,
  `agent.reasoning.delta`, `agent.heartbeat` (every 2 s while waiting, with
  what is awaited: model, tool, approval), `tool.call.started` (id, tool,
  tier, one-line summary, repairs), `tool.call.finished` (id, ok, duration,
  result summary, truncated flag), `diff.proposed` (path, hunks with ids),
  `diff.reviewed` (hunk id, decision), `change.applied` (paths, checkpoint
  id), `approval.requested` (id, exact action, tier, reason, choices),
  `approval.resolved`, `cost.updated` (tokens in and out by purpose, running
  total, context used and limit), `mode.changed`, `error.surfaced` (message,
  hint, workspace state, log path), `notice`;
- no event carries a traceback or a secret; text deltas are split only at
  UTF-8 character boundaries; kinds are additive within a major version and
  consumers ignore unknown kinds;
- a test fails if the loop module writes to stdout or stderr.

The trace event log (`EventKind`, hash-chained) keeps recording the audit
facts: `tool.invocation.*`, `step.*`, `checkpoint.created`,
`checkpoint.restored`, `agent.budget.exhausted`. Session events are the view;
trace events are the record.

### D8. Large files and large repos

- Ranged reads (D4) are the default the system prompt teaches.
- `repo_map` returns a symbol outline. It reads the v0.5 symbol index when
  `ract memory init` has built it, and otherwise parses with tree-sitter
  (already a hard dependency) for the five supported languages and lists
  file names and sizes for the rest.
- Context budgeting: near the provider's context limit, tool results older
  than the last few turns are replaced by a one-line summary with the path,
  line range and digest, which the model can re-read. The plan, the step
  contract, the digests of files edited in this step and every Rootknot
  artifact reference are never compacted.

## Compatibility

- Existing `ract.yaml` files keep working; the `agent:` block is optional
  and every key has a default. `tool_calling` defaults to `auto`.
- Existing sidecars verify unchanged. Sidecars for applied hunks use the
  current Rootknot schema (v4); no schema change.
- `tests/security` keeps passing; the resolver adds tests there.
- No new runtime dependency. `src/ract/tools/` uses the standard library,
  Pydantic and tree-sitter, all already declared, so the import allowlist in
  `tests/test_public_provenance.py` does not change.
- Every commit that changes `src/ract/` re-locks the source digest.

## Threats this introduces and how each is closed

| Id | Threat | Control | Test home |
|---|---|---|---|
| FS-1 | Path escape (`..`, absolute, symlink, junction, UNC, device names, ADS, 8.3, `/proc/self/root`) | D2 resolver | `tests/security/test_tool_paths.py` |
| FS-2 | Swap a path component for a symlink between check and write | No-follow open, final-path check, temp file and `os.replace` | same |
| FS-3 | Tier-1 write that becomes code execution (`.git/hooks`, `.git/config`, `.ract/hooks`) | D3 refusal | `tests/security/test_tool_protected_paths.py` |
| FS-4 | Model edits its own instructions, config or another agent's config | D3 refusal and tier 2 | same |
| FS-5 | Model writes executable configuration that runs later | D3 tier 2 with diff; ADR-0048 D4 re-approval | same |
| FS-6 | Read a secret and send it to the provider | Sensitive-pattern refusal, snapshot exclusion; outbound secret scan is section 7 | `tests/security/test_refuse_list.py` |
| FS-7 | Resource exhaustion: huge file, deep tree, regex blowup | Caps, child-process grep fallback with timeout | `tests/tools/test_read_caps.py` |
| FS-8 | Prompt injection inside a file asks for a dangerous action | Data blocks, trust labels, tier gate (ADR-0048 D9) | `tests/security/test_injection_file_content.py` |
| FS-9 | Model rewrites tests or graders to pass | G5 at commit (unchanged) | existing G5 suite |
| FS-10 | Runaway loop and cost | D5 budgets and loop guard | `tests/executor/test_step_agent_budgets.py` |
| FS-11 | Agent output clobbers the operator's concurrent edits | D6 digest check on apply | `tests/executor/test_apply_to_workspace.py` |
| FS-12 | Replacement characters written into a non-UTF-8 file | D4 encoding rule | `tests/tools/test_edit_encoding.py` |
| FS-13 | Tool markup accepted as an answer and written to disk | `tool_calls.extract` | `tests/test_tool_calls.py` (exists) |

## Rejected alternatives

- **Let the model write to the live tree directly.** The v0.3 shape that
  ADR-0011 retired. Crash consistency, per-step rollback and review before
  apply would all be lost.
- **Classify tool calls by their text, as plan prose is.** Tool names and
  arguments are structured, so a declared tier is exact and testable. Text
  matching would let a tool named `read_notes` that writes files pass as
  tier 0.
- **Resolve-then-check only, with `..` allowed.** Every escape class would
  become a property of `realpath` on three platforms. Refusing `..`
  lexically removes one class before the disk is touched.
- **Edits without a digest precondition.** The model would edit files it has
  not read, or files that changed under it, and the failure would surface as
  a wrong patch.
- **A worktree for every step, read-only ones included.** Correct and
  simple, but it costs seconds per question on large repositories and buys
  nothing when nothing is written.
- **Apply first, review afterwards with undo.** Faster for trusting users,
  and auto-accept mode offers exactly that. As the default it would put
  unreviewed changes in the operator's files.
- **Merge the step's diff into files the operator changed.** A three-way
  merge into a file someone is typing in produces surprises. Saving the
  patch and saying so never loses work.
- **Guess native tool support from the model name.** Names are unreliable
  across local servers and templates. A probe answers the actual question.

## Consequences

- RACT can work on a real repository: find, read in pieces, edit in place,
  review, apply, undo.
- Every file change keeps the v0.4 guarantees (worktree isolation, Rootknot
  sidecars, anti-lazy gates, rollback) and gains review before apply and an
  undo record against the live tree.
- Two defects that exist today (`..` in the diff applier and artifact
  writer) are closed by the first module, before any new capability.
- The tool registry and the event stream become the surfaces that MCP,
  hooks, subagents and the SDK plug into later.

## Negative and follow-ups

- Context compaction (D8) is mechanical here. Model-written summaries stay
  deferred (ADR-0046).
- LSP diagnostics after edits are section 8.
- FS-6 and FS-8 are fully closed only when the outbound secret scan
  (section 7) and the trust rule (ADR-0048 D9) land.

## References

- ADR-0004, ADR-0006, ADR-0009, ADR-0011, ADR-0012, ADR-0041, ADR-0046, ADR-0048
- `src/ract/executor/steps.py`, `src/ract/executor/tool_gate.py`,
  `src/ract/core/threat_model.py`, `src/ract/diff_applier.py`,
  `src/ract/model_output.py`, `src/ract/tool_calls.py`, `src/ract/rooted.py`
- `docs/THREAT_MODEL.md`, section "v0.6 agentic execution amendment"
