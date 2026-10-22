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
prompt test does. A repository cannot add or change a role: roles load from
the package only.

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
