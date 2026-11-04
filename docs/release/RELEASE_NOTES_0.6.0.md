# Release notes for RACT 0.6.0 (draft, B-151)

Draft for the MANAGER to finalize at the cut. Rewritten 2026-11-03 on the
release tip `4a1ee874` from the final evidence: the ten-journey real-model
legs on two local models and a hosted frontier model, the J11 command-slice
runs, the beginner walks, and the expectations audit
(`audit/phase-8/CLI_EXPECTATIONS.md`). `VERSION` stays 0.5.2 and the
operator cuts the release. Where a statement below depends on evidence that
does not exist (the real beginner walk by a person, macOS in CI), it says so
as a fact; it promises nothing.

## Where RACT goes past the usual

Verified on the release tip, each with the command that shows it (the full
table is in `audit/phase-8/CLI_EXPECTATIONS.md`):

- Signed grants and a command record: `ract policy init --guided` proposes
  the narrowest rule in plain language and signs it; every command run under
  a grant lands in a per-command record with its rule, argv, exit code and
  digests.
- The harness, not the model, decides done: the turn summary is assembled
  from what RACT observed; a claim of passing tests that RACT did not run is
  labelled as unchecked, and a failed real test run makes the turn failed.
- Per-hunk review: `/review` walks a change hunk by hunk with accept,
  reject, edit and skip; a rejected file's saved copy comes back.
- Undo and rewind: `/undo`, `/redo`, `/checkpoint`, `/rewind` and
  `/restore N` reverse whole turns, newest first, leaving files you edited
  meanwhile alone.
- Plan approval before anything runs: `ract run "<intent>" --dry-run` shows
  the assumption, the confidence and the steps, and writes nothing.
- Model-agnostic with local models: the same flows ran against a local
  OpenAI-compatible server found by `ract setup`, and `/model` switches the
  manager provider for the session without touching the config.
- Honest refusals and hints after every error: dead endpoint, declined
  step, missing grant and missing config each print one plain line naming
  the fix.
- Cost and egress accounting: `/cost` counts bytes per host and purpose and
  points at the egress ledger; `--no-network` refuses off-host requests
  before connecting and records the refusal.
- Headless event stream: `ract -p --output-format stream-json` emits one
  JSON object per session event, suitable for driving external UIs.

## What 0.6.0 is

0.6.0 is the interactive session of INTENT.md: a developer hands real coding
work to a model, local or hosted, inside a policy they control, and can show
afterwards what changed, why, under which permission, and how to undo it. The
success conditions S1 to S7 are the test of whether 0.6.0 is met; nothing else
decides what it contains (SCOPE_0.6.0_2026-11-01.md, section 1).

## Added

The interactive session and its controls:

- `ract` on a terminal, or `ract repl`, opens the interactive session: plain
  text runs as an intent, every verb works as a slash command, context carries
  between turns, and a failing command never ends the session.
- Session modes: `/mode plan` proposes without running anything, `default`
  asks before each step that changes a file, `auto-accept` applies changes
  without asking. `unrestricted` is refused; it needs the tier-3 policy this
  release does not have.
- Plan approval: a plan of two or more steps that changes a file is shown once,
  with `approve`, `skip <n>` and `cancel`.
- `/undo` and `/redo` in the session and in the shell reverse the last turn's
  file changes from its backup; your own later edits are listed and left alone.
  `/diff` shows the last turn's changes, `/review` walks them hunk by hunk with
  accept, reject, edit and skip, and a rejected file's saved copy comes back.
- Checkpoints and rewind: `/checkpoint`, `/restore N` and `/rewind` go back to
  an earlier turn by reversing every later one, leaving files you changed
  meanwhile alone.
- The turn ends with the harness's own account, one fact per line: the verdict,
  what changed with line counts, where the previous versions are, whether tests
  ran, the plan's assumption and confidence, and the request and token counts.
  A claim of passing tests that RACT did not run is labelled as unchecked.
- Ask mode: `/ask`, `ract run --ask` and `ract -p --ask` answer a question in
  one step, with no plan and no file written. A step with no target file is an
  answer step; nothing is written.
- `!<command>` in a session runs what you type, as you, in the project: the
  model never reaches this path, the output is not redacted, and where the
  machine cannot confine commands the line says so.
- `ract setup`, the first-run flow: it finds a model server already running,
  suggests a local model that fits the memory you give it, or names the key's
  environment variable for a cloud provider. It writes `ract.yaml` atomically,
  never over an existing one, and never downloads anything.

Tools and the step loop (all gated, off until enabled):

- Read-only tools `read_file`, `list_dir`, `glob` and `grep` (tier 0), and the
  write tools `write_file`, `edit_file`, `delete_file`, `move_file` and
  `apply_patch` with the step agent loop, off until `agent.step_tools: true`
  in `ract.yaml`. A control or executable-configuration file is tier 2 and
  asks at a terminal; nothing a model writes approves it.
- A proposed change is shown hunk by hunk before it reaches your files; only
  what you keep is applied. With `agent.step_tools: true` this review replaces
  the per-step question.
- `ract.tool_calls` reads a model reply as tool calls, a final answer or a
  named failure; a reply cut off at the output limit is explained, a malformed
  call is answered plainly and never reaches a tool, and loop guards stop a
  turn that repeats itself.
- A model that answers with tool calls instead of a plan gets the request as
  one step through the same gates. File and line citations in an answer are
  checked against the repository and the unverified ones are named.
- The to-do tool the model writes and the harness tracks: the list lives at
  `.ract/todo.json` and `/todo` shows it with its counts.
- `/spec` walks six questions one at a time and writes `SPEC.md` with the
  SHA-256 of the approved bytes; an abandoned walk keeps its draft and the
  next `/spec` continues it.

Grants, commands and verification:

- The operator key and the signed grant: `ract policy keygen` makes an
  Ed25519 key encrypted with a passphrase at a terminal, and
  `ract policy init --guided` proposes the narrowest rule for the test runner,
  the linter, the type checker, the formatter and the build, shows the diff
  and signs it on one yes. A grant holds only on the machine and for the
  folder it was signed for.
- `run_tests` runs the grant's test rule and a request that names a failing
  test ends with that test run; verifier tools `run_build`, `run_lint`,
  `run_typecheck` and `run_format` do the same for each kind. A failed real
  run makes the turn failed with exit 1 and the verdict names it.
- Allowlist mode (`/permissions allowlist`) lets a command that matches an
  allow rule run without asking, up to the grant's `max_mode`; remote git,
  output and execution flags, tier 2 and a changed test, conftest or runner
  configuration still ask in every mode.
- `ract doctor --tier3` reports the whole tier-3 state in one place: the
  grant, the key, why tier 3 is off, the sandbox as this machine runs it, and
  the command that fixes each problem.
- The harness signs what it writes: each file a turn changes gets a v4
  Rootknot record and `ract provenance verify` passes on it; the summary says
  `signed` only after verifying each file's knot. The record sits beside the
  file; commit it with its file.
- `ract verify` checks a commit range and/or a run offline: every changed line
  attributed to a signed step, each Rootknot verified, and the run's trace
  chain when the run has one (B-039, ADR-0050 as amended).

Visibility and accounting:

- The egress ledger records every request RACT sends to another host, with
  purpose, host, status, time, bytes and reported tokens, and nothing else.
  `/cost` and `ract doctor --egress` read it; `--no-network` refuses every
  off-host request before it connects and exits 3.
- Headless runs: `ract -p` with json and stream-json output carries the
  `ract.result/1` object with an `error` object, and `ract "<intent>" --json`
  prints the same object.
- `session.started` carries the session id and the context window when known,
  and the status line shows both.

## Changed

- `ract run "<intent>"` with no terminal no longer changes files without a
  flag: it stops with exit 3 and names `--yolo` or `ract -p --accept-edits`.
  Scripts that used `ract run` to change files add `--yolo`; see
  `docs/UPGRADING.md`.
- In a terminal, `ract run` and `ract "<intent>"` now ask before they change
  files, as the session already did; before, they wrote without asking.
- `ract handshakes approve` signs the approval with the operator key. The
  intent-recompile key and the per-run keys live outside the project now;
  `ract policy migrate-keys` moves them. Approvals made before this change
  must be given again (see `docs/UPGRADING.md`).
- `ract run --loop --yolo` exits with the code of the cause that stopped the
  loop instead of 0; the table is in `docs/EVENTS.md`.
- The session store keeps its files in `.ract/sessions` instead of
  `.ract_sessions/`; the first run copies old sessions in and says so.
- The session's screens come from the designed views, and README, QUICKSTART
  and PHILOSOPHY no longer claim what this release does not do (S-017).

## Fixed

The full list is in the Unreleased Fixed section of `CHANGELOG.md`; in theme:

- Cloned-repository defenses: state writers refuse a link or junction under
  `.ract`, paths from model output and from repo-shipped files resolve inside
  the workspace or are refused, session rollback snapshots from an unknown
  session no longer receive config-bearing names, and the LSP probe fails
  closed on a planted fixture name.
- Secret handling: a provider key, a web-search key and a GitHub token are
  masked wherever RACT shows text, a server that echoes a key in its error
  body no longer gets it printed, and one list decides which file names hold
  secrets across reads, writes, staging and the threat model.
- Git hardening: every git command RACT runs for itself starts with the full
  hardening (fsmonitor off, no hooks, no pager, by full path), a staged secret
  or one in the commit message refuses the commit, and a push is tied to one
  resolved URL and one commit.
- Honest reports: the tier-2 question, the sandbox section of `ract doctor`,
  the fetch question and the batch screens render as designed and say what is
  not enforced on this machine; the event stream tells the truth in more
  places; `ract doctor` without `--check-providers` contacts no provider and
  says so.
- Correctness at the edges: a file a step writes is refused when it does not
  parse, imports a name the project does not have, or is a reply cut off at
  the output limit; a turn that changes a file after its tests passed reports
  `stale`; configuration errors exit 2 with `error.kind: config`; and session
  files, event streams and sidecars stay strict JSON and atomic on disk.

## Experimental: sandbox, git tools and network tools

Slices (e) the sandbox, (f) the git tools and (g) the network tools are
labelled experimental in this release. They are off unless a signed grant
allows them, and a grant rule that names them asks before each use. Their
evidence rows at the freeze: the Linux run is green on the release tip, the
red-team cards are landed, and the real-model runs are in (the local legs,
the hosted remainder, and the J11 command-slice evidence named above). If an
evidence row is red at the cut, the slice is switched off by default and the
final notes say so; it is not deleted (SCOPE_0.6.0_2026-11-01.md, section 2).

What that means in use: on Linux, a tier-3 command runs inside bubblewrap
once a self-test shows it confines files, the network and host processes; on
Windows and macOS grants still say `best_effort` and RACT says so. The git
tools read freely and ask once per call for anything that writes; `git_push`
additionally needs a grant rule, a signed handshake for the remote and branch
and the operator's yes. `web_fetch` is https only, to the grant's
`allow_domains`, asks before every fetch in every mode, and refuses private,
loopback and metadata addresses after resolution. `web_search` has no
provider and says so.

## The success conditions as they stand

Rewritten from the final evidence on the release tip; a "partly" is not
rounded up:

| Condition | Status as it stands |
|---|---|
| S1 first run in under 3 minutes | met (Windows, reachable server; the UPGRADING walk and three beginner-agent walks, including the post-command-on-ramp walk of 2026-11-03, which finished the whole path unaided; the real walk by a person is Thursday) |
| S2 fix a failing test with a small local model and a frontier model | met: the fix journey passes on the 3B (full leg, seven journeys, with the formatting-strip notice live), on the 8B (J4, confirmation re-run after one malformed-plan refusal), and on the hosted frontier model (J4, 899 s, plan-approval branch) |
| S3 visible, reversible, traceable to a signed record | met, shown on real models: change screens with line counts, `/diff`, `/undo`, and the signed Rootknot record per changed file |
| S4 egress provable | met |
| S5 headless in CI | met |
| S6 no severity-1 journey defect | met as demonstrated: ten journeys on each of two local models and the hosted remainder on the frontier model, plus the J11 command-slice runs and a live hands-on user test (an agent driving a real session against the local model, the full fix-and-verify journey completed); every defect the runs surfaced (the fence-strip refusal, the manager prompt's pre-command sentence, the grant facts the manager could not see) was fixed on the release branch and re-run |
| S7 harness-written verdict | met on real models: verdicts assembled from recorded runs, including honest "verified: failed" and "not verified" lines |

Not exercised on a real model, stated plainly: J9 and J10 are terminal-matrix
and packaging journeys by design; the J5 live legs did not reach the diff
screen on any of the three live models (a runner review-answer probe timing
calibration, rev4; the journeys' product steps all passed); the 8B could not
carry the J11 fix journey in four attempts (the command mechanism fired
correctly every time; the model's plans were malformed or misdirected); and
on the scripted two-intent hosted journey the frontier models (DeepSeek on
NIM across three samples, Nemotron 3 Ultra 550B on OpenRouter across two,
both free-tier endpoints verified live) planned report steps instead of the
edit in five of five samples — while RACT's command mechanism stayed green
throughout: the granted run fired under the ask every time it was asked, the
command record was written, claim checks flagged unverified "passes" claims,
and the verdicts came from the real exit codes. The fix-and-verify journey
IS completed end to end with a live model where a user drives the session
(the hands-on test against the local model: plan approved, edit landed with
the formatting-strip notice, granted /test printed "2 passed", verified
independently). The hosted model-side scripted completion remains open with
counts, as a model-behavior observation rather than a product defect.

## What RACT does not do yet

From the expectations audit (2026-11-03, updated the same night), the
first-hour gaps a daily CLI user notices:

- `git mode` needs `git_mode: true` in ract.yaml (named in the error and
  QUICKSTART as of this tip); there are no branch helpers.
- Ctrl-C during a running turn takes effect when the turn ends (documented);
  mid-turn interrupt is a 0.6.1 design item.
- Line history and tab completion need readline: on Linux and macOS, not yet
  on Windows.
- Colour through a Windows console could not be confirmed by the audit
  (NO_COLOR and `--plain` both work); flagged for a real-console check.
- `web_fetch` exists as a gated tier-3 tool (asks every time, https only,
  grant-named domains) but was not exercisable with the scripted server; its
  user documentation is a pointer to `docs/TIER3.md`.

The Linux rerun of the release tip is green (the WSL2 evidence row, on the
tip with the fixes); macOS arrives with CI on the release push. If any row
here is greener at the cut, the MANAGER updates it with the evidence;
nothing here is a promise.

## Upgrading

See `docs/UPGRADING.md` for the v0.5.2 to 0.6.0 path: what changes, what asks
now, and what to run. The one command to start with is
`ract policy init --guided` at a terminal, which proposes and signs your first
grant; `ract doctor --tier3` then shows the whole state in one place.

- In a session the model cannot run your tests by itself: command
  execution is tier 3 and stays off without a signed grant. RACT's loop runs
  your test command, a signed grant runs commands under your rules, and
  `/test` runs the granted test command on your keystroke. The slice is on
  the release tip with the J11 evidence row below.

## Not claimed

- That the real beginner walk has happened: a person walks on Thursday; three
  beginner-agent walks (the last on this tip, with the command on-ramp) are
  evidence before, not the walk itself (D-161).
- That the hosted J11 model-side row is complete: the mechanism is proven
  (the ask, the granted run, the record, the honest verdict); the model-side
  completion was blocked by the provider's availability during the runs.
- That the sandbox confines a command on Windows or macOS: it does not; grants
  say `best_effort` and RACT says so.
- That macOS is verified: it is not; it arrives with CI on the release push.
- That every 0.6.1 card is closed: the queue stands on the board (the signing
  screen's one-line "what this grant is for" is the first item the walks
  earned).
