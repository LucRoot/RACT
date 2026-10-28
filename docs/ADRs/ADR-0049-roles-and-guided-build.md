# ADR-0049: Roles and Guided Build

## Status

Proposed (v0.6). Design accepted for drafting by the operator on
2026-10-22. Code lands only for the ungated parts named in "Rollout": the
role definitions and their loader, the provider capability probe, the
EXPLORER role over the read-only tool slice, the VERIFIER result type wired
to the existing gates, and the playbook loader with the explain-code
playbook. Every role that writes files or runs commands stays design-only
until the operator ratifies the tool layer beyond the read-only slice
(ADR-0047) and tier 3 (ADR-0048).

## Context

Through v0.5.2 a plan step is one chat completion. A weak local model fails
there because nothing carries it from a request to a verified change: it
must find the code, decide the change and produce the whole file in one
answer. A strong model loses effort for the same reason. Two pieces already
exist and are not on the session path:

- The memory-discipline functions (`src/ract/memory/functions/`): `intake`,
  `research`, `plan` and `edit`, each with a typed contract
  (`contracts.py`: WorkOrder, ResearchBundle, ChangePlan, CandidateDiff), a
  versioned prompt (`prompts/*_v1.md`), a token budget
  (`memory/budget_defaults.yaml`) and playbooks in YAML
  (`memory/playbooks/`). The composition runner reaches them only through
  the loop controller's optional `composition_runner`.
- The Manager and Executor split (`manager.py`, `executor/steps.py`): the
  Manager returns a Rooted plan, the Executor runs each step, the harness
  writes the verdict (B-038).

The intent says the model never declares done. This ADR names the roles
RACT gives a model, maps each onto what exists, and decides who decides
done.

## Decision

### D1. The role set

| Role | Job | Maps onto | Model class | Tools (tier) | Ungated now |
|---|---|---|---|---|---|
| INTAKE | Restate the request and pick a playbook | memory `intake` (WorkOrder) | either; a deterministic fallback from `request_type` keywords | none | data and loader |
| EXPLORER | Read, search, answer questions | memory `research` (ResearchBundle) plus the read-only tools | either | `read_file`, `list_dir`, `glob`, `grep` (T0); `repo_map` is gated with B-010b until the OPERATOR names it | the four tools: yes, after S-028 and the Linux symlink run |
| PLANNER | A Rooted plan: assumption, confidence and acceptance checks per step | Manager plan, extended with ChangePlan `verification_criteria` | strong preferred; weak with schema output | none | prompt and schema |
| EDITOR | One change inside the policy | memory `edit` (CandidateDiff) through ADR-0047 write tools | either | `edit_file`, `write_file`, `apply_patch` (T1) | design only |
| VERIFIER | Run tests, lint and type checks; report structured results | ALM gates G1 to G5, coverage and mutation gates | none: harness code, no model | `run_tests`, `lint`, `typecheck` (T3, ADR-0048) | result type, wired to coverage and mutation gates only |
| REVIEWER | Read the diff, report findings with file and line | G7 companion provider | strong preferred | read-only (T0) | design only |

**Cut: SUMMARIZER.** The turn summary is assembled by the harness from
events (B-038). A model that summarizes would put a model's claim back where
the operator reads facts. Model prose stays below the summary under the label
`model summary`.

**VERIFIER is not a model role.** It is harness code. A model can propose
which command checks a step (the PLANNER's acceptance checks); only the
harness runs it and records the result. This keeps invariant 8: no role's
text approves its own work or a tier-2 or tier-3 action.

### D2. Each role as data

One file per role in `src/ract/roles/<role>.yaml`, shipped in the package:

- `purpose`: one sentence.
- `input` and `output`: the schema names (the contract types above and the
  new ones in D3), each delivered as `Rooted[T]`.
- `tools`: the allowlist with tiers. The loader refuses a role whose tool
  tier exceeds what is ratified (today T0).
- `budget`: a key into `memory/budget_defaults.yaml`.
- `model_class`: `weak`, `strong`, `either` or `none`.
- `prompt`: a file under `src/ract/roles/prompts/` with a version suffix.
- `checklist`: the per-step items the harness checks on the output (for
  example "every named file exists", "every acceptance check names a
  command or a predicate").
- `stop`: the condition that ends the role (an answer that passes the
  checklist, a budget, or a refusal).
- `failure_modes`: named failures with the next action (retry with the
  error, escalate, or stop).

Golden tests pin the prompt sentences real models see, as the manager
prompt test does. Built-in roles load from the package. A repository role
file is hostile input; D11 states the only way one loads (narrowing a
built-in role, in a trusted repository).

### D3. Handoffs are artifacts

Roles pass typed artifacts, never free prose:

| Artifact | Produced by | Consumed by | Exists |
|---|---|---|---|
| WorkOrder | INTAKE | EXPLORER, PLANNER | yes (`contracts.py`) |
| ResearchBundle | EXPLORER | PLANNER | yes |
| Answer (text with cited `path:line`) | EXPLORER | the turn (explain playbook) | new |
| Plan with acceptance checks | PLANNER | EDITOR, VERIFIER | extends `manager.Plan` |
| CandidateDiff | EDITOR | VERIFIER, REVIEWER, review and apply (ADR-0047 D6) | yes |
| VerificationResult | VERIFIER (harness) | turn summary, anti-lazy gates | new; the `verification` object of `turn.finished` |
| ReviewFindings | REVIEWER | the operator (advisory) | new |

Artifacts are stored per turn in the user state directory, keyed by the
repository like the undo store (S-028), never under the workspace's
`.ract/`, so a repository cannot plant one. They are signed when the
provenance wiring lands (S-015b); until then the summary says "unsigned".

**An acceptance check is a proposal, not a command.** The PLANNER (a model)
and a playbook propose the checks the VERIFIER runs. A proposed check is an
argv list, never a shell string. The harness runs it only when it matches
the operator's command policy (ADR-0048, gated); any other check is shown
to the operator and not run. A check that comes from a repository playbook
is a trust item (S-025), like a hook's command: it is listed by `ract trust`
and is part of the trust digest.

### D4. Who decides done

A step is done when a VerificationResult recorded after its last edit
passes and the anti-lazy gates pass at the commit boundary (ADR-0047 D5,
termination T1). A role output that claims success without that record
leaves the turn `unverified`, and the summary says so (B-038 already flags
"tests pass" claims; a test plants a role output claiming success with no
VerificationResult and checks the turn is marked unverified).

An answer step (explain code, a question) changes nothing, so it has no
VerificationResult. Its done-ness is "citations verified" (B-037): every
`path:line` it cites exists and the quoted text is at that line. An answer
with no citation, or with a citation that does not check out, leaves the
turn `unverified` in the summary.

### D5. Weak-model guidance is mechanism

- Smaller steps: playbooks split a change into one EDITOR step per file.
- Schema-constrained output: each role's output is parsed against its
  schema; JSON mode or grammar where the provider supports it (from the
  capability probe), the B-017 extraction ladder otherwise.
- A per-step checklist the harness checks (D2); a failed item goes back to
  the model as the error.
- Bounded retry: at most two retries per role call, each with the parse,
  checklist or test error as context; then the role stops with a named
  failure and a hint. That error text can contain repository text (a test's
  output, a file's line), so it passes the outbound secret scan (S-022)
  before it is sent and is labeled in the prompt as untrusted output, not
  as an instruction.
- The single-shot path stays for steps that only produce text (answers).

### D6. Strong-model path

Fewer, larger steps (the playbook may merge PLANNER and EDITOR steps for a
strong model), native tool calling, and parallel EXPLORER work in separate
read-only contexts (no worktree is needed for reads, ADR-0047 D6).

### D7. Playbooks are data

The existing YAML format (`memory/playbooks/`) gains `roles` (an ordered
list) and `acceptance` (the checks that end the playbook). Six playbooks:
bug fix, add a feature, refactor, add tests, explain code, review a diff.
Explain code needs only INTAKE and EXPLORER and ships first. A repository
may add playbooks only when it is trusted (S-025); package playbooks cannot
be overridden.

A repository playbook is a workspace file, so its loader is written as
hostile-input code: one fixed directory (`.ract/playbooks/`), each name
checked with `undo_backup.require_name`, `yaml.safe_load` only, a size cap
(64 KiB per file), schema validation before any field is used, and the
bytes of every playbook file inside the trust digest, so a changed playbook
ends trust like a changed hook.

### D8. Router: a model per role, explained

`ract.yaml` gains an optional `roles:` map from role to provider name. The
default is the manager provider for INTAKE and PLANNER and the executor's
routing for EXPLORER and EDITOR. `/model` shows each role's provider, model,
capabilities (from the probe) and cost so far; `/model <role> <provider>`
switches one role for the session. When a role's `model_class` is `strong`
and the assigned model probed weak (no native tools, small context), the
session says so once and continues on the weak path.

**Role routing is egress.** A `roles:` entry can send repository content to
a different provider. Each role call is recorded in the egress ledger with
purpose `role:<name>`. `/model` shows each role's host. A role assigned to a
host that is neither loopback nor one the operator chose needs the same
trust as a repository-named provider (S-030: a `network` trust item).
`/model <role> <provider>` accepts only a provider that exists in the
configuration.

### D9. Large outputs are offloaded; the model reads slices

A 7B-class model with an 8k window cannot take a 200 KiB test log, and
pasting one in would push out the plan and the file being edited. So:

- **Threshold: 8 KiB** for any single output that would enter a model
  request (a test or check log, a tool result, a search result, a file
  read). 8 KiB is about 2,000 tokens, a quarter of an 8k window. Smaller
  outputs go in whole.
- **Where it lives.** A larger output is stored whole as an artifact of
  the turn in the user state directory, beside the D3 artifacts, never in
  the workspace. It is signed when provenance wiring lands (S-015b).
- **Who summarizes: the harness, never a model.** The summary holds the
  exit status, the total lines and bytes, for a test run the failing test
  ids (the runner's own summary lines), then the first 20 and the last 40
  lines, capped at 4 KiB, and the pointer `artifact:<turn>/<name>`. A model
  summary would put a model's claim where the user reads facts (the reason
  SUMMARIZER was cut).
- **`read_slice(target, start_line, end_line)`** joins the read-only slice
  (ADR-0047 D1, after B-010a, which creates the slice's tools). The target
  is an artifact pointer of the current run or a workspace path. One call
  returns at most 200 lines and 16 KiB. A workspace path goes through
  `workspace_path` for reading and the send rule (`.git`, `.ract` and
  secret-named files are never sent); a pointer resolves only inside the
  run's artifact folder, its name checked with `require_name`. A file
  with a NUL byte in its first 8 KiB is refused as binary. The returned
  text passes the outbound secret scan (S-022) before it enters a request.
- **What a 7B model with an 8k window sees on a failing run:** one line of
  exit status and size, the failing test ids, the last 40 lines (where
  pytest prints the assertion), the first 20, and the pointer. About 1,500
  tokens. It asks `read_slice` for more only when it needs it.

Tests (named now, written with the code): `test_a_5_mib_log_reaches_the_model_as_a_bounded_summary`,
`test_read_slice_refuses_parent_segments_absolute_and_protected_paths`,
`test_read_slice_refuses_a_binary_file`, `test_read_slice_returns_at_most_200_lines_and_16_kib`,
`test_read_slice_pointer_cannot_leave_the_run_folder`.

### D10. The model never ends the loop; the limit stops and asks

**A loop never ends because the model says it is finished.** Many agent
designs end when the model emits a completion tag; RACT does not. Done is
decided by the VERIFIER's recorded result and the anti-lazy gates (D4,
INTENT invariant 8). A reply that contains "task complete", "TASK_COMPLETE"
or any other tag has no effect on control flow: it is answer text, and a
success claim in it is reported as unverified (D4).

**At the limit RACT stops and asks.** When `--max-iterations` or the
per-role retry bound (D5: two retries) is reached, RACT stops and shows:
the last verifier summary (as in D9), the files the turn touched with line
counts, and the number of attempts. On a terminal it asks: retry with a
note, edit the plan, or stop (the default). A retry the user chooses runs
one more round of the same size, recorded as an event by the operator.
RACT never loops silently and never raises its own limit. Without a
terminal it stops with outcome `budget` and exit 4, and the same context is
in the result.

Tests: `test_a_completion_tag_does_not_end_a_run_with_a_failing_result`,
`test_the_loop_limit_stops_with_context_and_waits`,
`test_headless_loop_limit_exits_4_with_context`,
`test_no_role_output_widens_the_retry_bound`.

### D11. Roles from a repository are hostile input (S-033)

A role file inside a cloned repository was written by the repository's
author. It is the same class of input as the hooks defect (S-025) and the
path defects (S-028), and a role carries levers: a prompt, a tool
allowlist, a tier and a model. The role loader card stays blocked until
these rules are accepted.

1. **Built-in roles are pinned by the source digest.** They ship as package
   data the digest covers; editing one changes the digest.
2. **A repository role loads only through the trust store.** Each file is a
   trust item of kind `role`, listed by `ract trust`, and its bytes are in
   the trust digest; one changed byte makes the repository untrusted again.
3. **It narrows, never widens.** A repository role names a built-in role and
   may remove tools from its allowlist or lower its tier. It cannot add a
   tool, raise a tier, change the model or provider, or turn off a gate.
4. **Limits and schema.** At most 16 KiB per file; a closed set of keys (an
   unknown key is an error naming it); the name checked with
   `require_name`; `yaml.safe_load` only; no includes. Prompt text from a
   repository role goes into a labeled block of data and never overrides
   the rules in the system prompt.
5. **No field is a command.** Nothing in a role is executed, passed through
   a shell or used as an argv. Acceptance checks a role proposes are
   proposals (D3) and run only under the ADR-0048 policy.
6. **One fixed directory.** The loader reads `.ract/roles/`, resolved
   through `workspace_path`, and never a path named by another file. A
   symlink that leaves the project is refused.

Tests: a repository role that adds a tool, raises the tier, or names a
command is refused with the key named; an unknown key, a 1 MiB file, the
name `../x`, and a symlink to a file outside the project are each refused
with a plain message; untrusted, it is not loaded and `ract trust --list`
shows it; trusted and then changed by one byte, it is untrusted again; an
edited built-in role fails the source digest test.

### D12. Plan approval (B-064a; decision O is yes, D-051)

The user sees the whole plan once and decides before any step runs. This
section is designed to the recommendation for decision O; the end of the
section says what changes under the other answers.

**When it asks.** In `default` mode, when the plan has two or more steps
and at least one of them changes a file. It never asks in `auto-accept`
(changes apply without asking) or in `plan` (nothing runs), and never for
a plan of answer steps only. A one-step plan keeps the per-step question.

**The answers.** Typed at one prompt, shown under the same `[ ]` lines the
plan checklist uses (B-053a, one renderer):

- `approve`: run the plan as shown.
- `skip <n>`: drop step n and every step that depends on it, and name them.
  Step m depends on step n when m targets the file n targets, or m's action
  names n's target path. That second test is a text match on model text, so
  it can miss a dependency; a missed one fails safe (the dependent step
  fails with a plain error and writes nothing it should not), and since the
  dependents found are named, the user can skip more. A skipped step is
  reported as "skipped by you".
- `edit <n>`: change step n's text or target once. The edited plan goes
  through the plan validator, the workspace path rules and `answer_instead`,
  and is shown again; nothing has run. No model is called for an edit.
- `cancel`: nothing runs and no file changes; in a session the turn ends
  with outcome `refused` (an existing `turn.finished` outcome) and exit 0.

Nothing the user types is run: an edited step is data for the validator,
and every string shown passes `safe_text`.

**After approval.** A step whose target is on the approved plan runs
without asking again. A step that would write a file the approved plan did
not list (a diff that touches another file, for example) still asks, so an
approval covers exactly what the user saw. The approval replaces only the
question. An approved step still passes every gate: the write gate, the
path rules, the secret scan, the tier checks and the trust store.

**`plan_hash`** is the sha256 of the canonical JSON (sorted keys) of the
steps' `n`, `action` and `target`. The assumption and confidence are left
out, so a re-planned plan with the same steps does not ask twice.

**Events** (added to `docs/EVENTS_SESSION.md` when the code lands, after
the MANAGER reviews this list):

| Kind | Fields |
|---|---|
| `plan.approval_requested` | `plan_hash` (string, as defined above), `steps` (as in `plan.proposed`) |
| `plan.approval_answered` | `plan_hash`, `answer` (`approve`, `skip`, `edit`, `cancel`), `kept` (list of step numbers), `skipped` (list of `{n, reason}`, where reason is `user` or `depends on step <k>`), `edited` (step number or null) |

An `edit` emits `plan.approval_answered` with `answer` `edit`, then a new
`plan.proposed` and a new `plan.approval_requested` with the new hash.
Consumers that read only `plan.proposed` see nothing different.

**Headless.** `ract -p` has no terminal, so it behaves as D-030 decided: in
`default`, a plan with a file change is refused (exit 3, the hint names
`--accept-edits`); with `--accept-edits` it runs without asking. No
`--approve-plan` flag.

**Resume.** A resumed session that already approved a plan with the same
`plan_hash` does not ask again; a changed plan asks.

**If decision O is answered differently.** If the OPERATOR keeps per-step
questions only: `plan.approval_requested` is never emitted, and nothing
else in this section changes. If the OPERATOR wants approval for every plan,
including one step: the threshold drops from two steps to one and the
per-step question for a one-step plan goes away. The event shape is the
same under every answer.

Tests: event order and fields; `skip` of a step another step depends on
(the dependent is skipped and named); an edit that fails validation (the
plan is shown again, nothing ran); `cancel` leaves the workspace byte for
byte as it was; hostile step text (escape codes, a 10,000-character line)
is clean on screen and in the events; headless `default` refuses with exit
3; resume with the same plan hash does not ask twice; a step writing an
unlisted file still asks; old consumers of `plan.proposed` are unaffected.

### D13. A checkpoint after every step, so a killed run resumes (B-070)

A run saved its session record once, after the last step. A run killed
during step 2 of 3 left files on disk and no record of which steps had
finished, so nothing could be resumed (found in B-066).

**Where.** One file per run in the user state directory, beside the undo
store and keyed by the repository the same way:
`<state>/runs/<repository key>/<run id>.json`. It is never written under the
workspace, so a cloned repository cannot ship one. It is still read as
untrusted data: the run id passes `require_name`; a symbolic link is
refused; at most 256 KiB; a closed schema (an unknown key, a missing key or
a wrong type refuses the file); the `root` field must equal this
repository's key.

**When it is written.** When a step starts, before it touches any file
(`in_progress` set); when the step saves a file it is about to replace or
create, before the write; when it has written that file; and when it
finishes (`finished` updated, `in_progress` cleared). A kill at any point
leaves a record of what to reset. On the worktree path the step is
recorded, with its step id, before its worktree exists, and it finishes
only when its changes have reached the user's files, not when the executor
finishes inside the worktree.
Every write is atomic: a temporary file in the same folder, flushed, then
replaced over the old one, so a kill during the write leaves the previous
checkpoint whole. A truncated or unreadable file is refused, never trusted.

**What it holds:** `schema` (`ract.checkpoint/1`),
`root`, `run`, `intent`, `plan` (assumption, confidence and the steps as in
`plan.proposed`, each with its `provider_hint` and `tool_call` so it can run
again), `plan_hash` (D12), `finished` (step numbers whose `step.finished`
outcome was `done`), `in_progress` (null, or the step number that started
and did not finish, with the turn backup's `backup_id`, the step's
`worktree` id on the worktree path, and the files that step had saved or
created so far, each with its sha256 `before` the step, its sha256 `after`
the step wrote it, and whether it was `written`).

When the step saves a file, a copy of the file as it was at that step's
start is kept in the turn's backup folder (under `.ract/steps/<n>/`, a name
no workspace path can take). The turn backup keeps a file's bytes once per
turn, from before the first step that touched it, so restoring from it
would also undo an earlier finished step's change to the same file.

**Finished** means the harness recorded `done` for the step: never the
model's word, never a claim in a reply (D10).

**Resume.** `ract run --session <run id> --resume` (the flag that already
exists). A one-shot run without `--session` gets a generated run id and,
when it stops early, prints the command that resumes it. On resume:
1. The checkpoint is read with the rules above. A plan whose recomputed
   `plan_hash` differs from the stored one is not trusted: the run says so
   and does nothing.
2. The stored plan goes through the plan validator, the workspace path
   rules and `answer_instead` again, as a new plan would. `plan_hash`
   covers each step's `n`, `action` and `target` only, so a stored
   `provider_hint` and `tool_call` are trusted no further than a new
   plan's: once a tool call can run (B-010a), a resumed step's `tool_call`
   passes the plan validator and the tier gates again before it runs, with
   a test that a changed stored `tool_call` is refused (G-150).
3. The step in progress is reset. The substrate path removes its worktree
   and step branch with the existing cleanup. The direct path restores what
   that step saved and removes what it created, through the undo helpers;
   a file the user changed since is left as it is and named, as `/undo`
   does. A file the step saved but may not have written (no `after`) and
   that differs from `before` is treated the same way: left and named.
4. Finished steps are not rerun; the rest run in order.
5. A plan already approved under D12 with the same `plan_hash` is not asked
   about again.

**What the user sees,** one line per step before anything runs:
"step 1 done earlier, not run again", "step 2 was interrupted; its partial
change was undone; running it again", "step 3 next". These are `notice`
events, so no new event kind is needed, and no config key.

Tests (named now): `test_a_checkpoint_exists_after_step_1`;
`test_in_progress_is_recorded_before_the_step_touches_a_file`;
`test_a_truncated_checkpoint_is_refused`;
`test_the_users_edit_to_a_file_the_interrupted_step_touched_survives`
(byte for byte);
`test_a_corrupted_oversized_linked_or_foreign_checkpoint_is_refused_and_never_run`;
`test_a_plan_hash_mismatch_is_not_trusted`;
`test_resume_never_reruns_a_finished_step` (requests counted at the fake
server); `test_no_half_written_file_remains_after_resume`; WRIGHT's B-066
journey test runs on the one-shot path once this lands.

## Model integration

- **Capability probe.** Chat, streaming, native tool calling (one request
  with a trivial `echo` tool), reasoning content, and context size (from
  `/models` metadata where the server reports it, otherwise unknown).
  `ract doctor --check-providers` runs the probe live and prints each
  capability with a plain next step for each gap (B-056); it writes no
  cache. The probe requests are recorded in the egress ledger under
  purpose `probe`.
- **Capability cache.** ADR-0047 D5 placed it in `.ract/capabilities.json`;
  that file is repository-shippable, so this ADR moves it to the user state
  directory. It stores facts only (booleans, a context size, a timestamp),
  never a response body, keyed by provider URL and model. It is its own
  small card after this ADR is settled.
- **`/model`** as in D8. **Reasoning effort**: a session setting (B-057) and
  a `reasoning_effort` key in `ract.yaml` (off, low, medium, high; B-057b),
  mapped to a provider's parameter only where documented, off by default.
- **Retry and rate limits**: backoff with jitter; `Retry-After` honored up
  to 120 s; a refused local connection fails fast (B-043); a 429 waits with
  the plain message "the provider is rate-limiting; trying again in N s
  (attempt K of M)" (B-055).
- **Local help**: `ract doctor` explains a model too large for the machine
  (the setup memory guidance), a context too small for the repo map (with
  the setting to raise), and a server without tool calls (with the
  fallback that will be used).
- **Cloud help**: the key variable is set (never printed), the host pairing
  holds (S-025 key binding), one tiny request succeeds.
- **Presets**: llama.cpp (router mode), Ollama, LM Studio, vLLM and the main
  cloud providers, each tested against the fake model server. The preset
  table marks which have also run against a real server; none have until
  the operator provides `RACT_DEMO_BASE_URL` and `RACT_DEMO_MODEL`.

## Rollout

Ungated, in order, each its own commit with tests:

1. Role definitions, schemas and loader, with golden prompt tests.
2. The capability probe and the `doctor --check-providers` report.
3. EXPLORER over the read-only tool slice, after S-028 is committed and the
   symlink refusals have run on Linux (B-046).
4. The VERIFIER's `VerificationResult` type, wired to the coverage and
   mutation gates only. It runs no new commands.
5. The playbook loader and the explain-code playbook.
6. The offload store and the harness summary (D9), about 2 hours.
7. `read_slice` (D9), about 3 hours, after B-010a.
8. The loop-limit stop and the completion-tag test (D10), about 2 hours,
   with the loop runner.
9. Repository roles under the D11 rules, about 3 hours, after the role
   loader (item 1) and the MANAGER's acceptance of D11.

Design only until ratified: EDITOR, the command-running VERIFIER, REVIEWER
calls that send diffs to a second provider, and anything at tier 2 or 3.

## Dependence on gated decisions

| Part of this ADR | Depends on | State |
|---|---|---|
| Role data, loader, golden prompts (D2) | nothing gated | ungated |
| INTAKE and PLANNER prompts and schemas | nothing gated (no tools) | ungated |
| EXPLORER (D1) | ADR-0047 D1 to D4 for T0 tools only, the read-only slice | ratified 2026-10-22 with two conditions: S-028 committed, symlink refusals run on Linux (B-046) |
| `repo_map` for EXPLORER | B-010b | gated until the OPERATOR names it |
| Running a proposed acceptance check (D3) | ADR-0048 command policy | gated; until then a check is shown, not run |
| Repository playbooks (D7) | S-025 trust and the hostile-input loader in D7 | ungated design; the loader is its own card |
| `roles:` routing to a host the operator did not choose (D8) | S-030 network trust | ungated design; uses the existing trust items |
| Offload store and harness summary (D9) | nothing gated | ungated |
| `read_slice` (D9) | B-010a (the read-only slice's tools) | after B-010a |
| The loop-limit stop (D10) | the loop runner and the VERIFIER record | ungated design; code with the loop |
| Repository roles (D11) | S-025 trust store; the role loader | rules accepted first; loader after |
| Plan approval (D12) | decision O: yes (D-051); B-053a checklist renderer | approve, skip, cancel, the two events and the headless refusal are wired; `edit` is not built yet (it asks again) |
| Step checkpoints and resume (D13) | nothing gated; undo helpers (S-028) and the D12 plan hash | built (B-070) |
| VERIFIER result type (D3, D4) | the existing coverage and mutation gates | ungated |
| VERIFIER running tests, lint, type checks | ADR-0048 D5 `run_command` and tier 3 | gated |
| EDITOR | ADR-0047 D1, D4 write tools (T1) and D6 review and apply | gated |
| REVIEWER sending a diff to a second provider | ADR-0048 (approvals) and the egress rules | gated |
| Capability probe, `/model`, setup help (Model integration) | nothing gated; the probe is one visible request per provider | ungated |
| Playbooks other than explain code | EDITOR and the command-running VERIFIER | gated |

## Consequences

- One framework: roles are names and data over the memory functions and the
  Manager and Executor split.
- The environment decides done in every playbook; no prompt can change that.
- Role artifacts and the capability cache leave the workspace, closing the
  same class of planted-file risk as S-028.

## Negative and follow-ups

- Two plan types exist today (Manager `Plan` and memory `ChangePlan`); D3
  extends the Manager plan with the acceptance checks and leaves ChangePlan
  as the EDITOR's per-file input. Merging them is a later change.
- Parallel EXPLORER work raises provider rate-limit pressure; the router
  limits concurrency per provider.
- Real-model evidence for the presets waits for the operator's endpoint.

## References

- `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`, function contracts and
  playbooks.
- ADR-0047 (tool layer and step agent loop), ADR-0048 (tier 3 and
  approvals).
- B-038 (harness turn summary), S-025 (repository trust), S-028 (undo
  store outside the workspace).
