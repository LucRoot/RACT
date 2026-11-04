# UX bar check (B-054 sweep, integ-check "Merge commit B-054f into work/mason/integ-check")

One line per numbered item in `BOARD/UX_BAR.md`: standards 1 to 13 and journeys J1 to J10.
Each status is backed by a capture or a test, named on the line. Where neither exists,
the status says so. Evidence paths are relative to this worktree.

Status words: **met**, **partly met**, **not met**. "Not run" means the journey could not be
walked in this batch, with the reason.

## Standards

1. **Feedback within 300 ms, sign of life at most every 10 s in plain mode: not met as written.**
   Adjudicated 2026-10-26 (`BOARD\ADJUDICATION_2026-10-26.md`, row 1): the plain-mode check line is
   "heartbeat at most every 10 s". The plain renderer prints the heartbeat every 10 s
   (`src/ract/session_render.py:52`, `_PLAIN_HEARTBEAT_EVERY_MS = 10_000`). The rich renderer's
   status row is the 2 s sign of life (not visible in the rich-mode captures; see the handoffs).
   Captures show `... waiting on model (4 s)` then steps of 10 s (`docs/ux/b054r/J4.txt`).
   No feedback is measured at submit; the 300 ms figure is not checked.
2. **See what the tool is doing (streaming, reasoning, tool cards): partly met.** Intents run as
   event-driven turns with a heartbeat (`src/ract/repl.py:139`). The `stream` setting defaults
   to off (`src/ract/repl.py:96`). No collapsible reasoning and no one-line tool cards exist.
3. **See what changed (readable diff, per-hunk accept/reject): partly met.** The turn shows a
   diff block (`docs/ux/b054/J4.txt`, lines 28 to 35; `src/ract/session_render.py:387`,
   `_on_diff_proposed`). Per-hunk accept or reject is not built (B-014c, see J5).
4. **Always a way back (one undo command, checkpoints listed): partly met.** `/undo` exists
   (`src/ract/repl.py:351`) and the turn names it: `way back: /undo` (`docs/ux/b054/J4.txt`).
   No capture walks an undo, and checkpoints are not listed with their changes.
5. **Always a way to stop (Ctrl-C, queue ahead): partly met.** Ctrl-C returns to the prompt
   within two seconds (`tests/test_session_turn.py:209`, `test_ctrl_c_returns_to_the_prompt_within_two_seconds`;
   `docs/ux/b054r/J6.txt`). The queue indicator and typed-ahead queueing are not built (B-033).
   Prepared, unwired (package J, `src/ract/ui/queue_view.py`, `tests/test_queue_view.py`): the indicator
   text, the `/queue` list and `/queue drop <n>` with their errors, at 80, 60 and 40 columns. The BUILDER
   wires them when B-033s lands. The proposed `input.withdrawn` fields are an ESCALATE in the log.
6. **Know where you are (model, provider, branch, context, tokens, cost, mode, tier, session id):
   partly met.** The status line shows model, provider, branch, mode and tier
   (`src/ract/session_render.py:158`; `docs/ux/b054r/J2.txt` line 2). Context use, tokens, cost
   and session id are not on it. `/cost` and `/context` carry those in separate screens.
7. **Errors say what to do (hint line, no traceback): partly met.** The error sweep ran 22 cases
   (`docs/ux/errors_check.md`, raw captures in `docs/ux/errors/`). 11 pass, 6 are partial, 2 fail,
   and the rest were not reached or cannot be reproduced here. No traceback appears in the error sweep's captures (`docs/ux/errors/`). Package T adds one: the Windows file capture for a locked file on the headless `ract -p` path still prints a traceback (`docs/ux/windows_files/results.json`; handoff H7 in `docs/ux/windows_files.md`).
   The partial and failing rows are named handoffs (`docs/ux/errors_check.md`, Handoffs section).
8. **No dead ends (nearest command, setup flow, refusal explains how to permit): partly met.**
   Setup flow walked to the end on the `Y` path: four questions, `ract.yaml` written, health check
   with a hint (`docs/ux/c_journeys/J1.txt`). An approval denial still gets the provider-check hint
   (error sweep row 22; handoff).
   `/resume` suggests the closest session id (`src/ract/session_listing.py:98`, `closest_id`).
   An unknown command now suggests the nearest one: `unknown command /hlep. Did you mean /help?`
   (`src/ract/repl.py`, `_handle_command`; tests in `tests/test_ux_gap_b.py`). The setup
   flow asks a question (`docs/ux/b054r/J1.txt` line 2) but was not run past the `n` answer.
9. **Permissions are understandable (exact change, reason, four choices): not met.** The
   approval prompt offers `[y/N]` only (`src/ract/approval_callback.py:35`). No allow-once,
   allow-for-session, allow-always or prefix choice exists.
10. **Works where users work (80 columns, dumb terminal, piped stdin, NO_COLOR): partly met.**
    Captures at 40 and 60 columns of the multi-line commands are in `docs/ux/width_a/`; the soak at 80
    and 60 columns is in `docs/ux/soak_g/`. Package H (`docs/ux/terminal_matrix.md`, captures in
    `docs/ux/terminal_matrix/`) ran the same journey in ConPTY direct, Windows PowerShell 5, PowerShell 7,
    cmd and Git Bash: box drawing, colour codes, 80-column width, Ctrl-C, a paste approximation, and code
    pages 437 and 1252 with non-ASCII text, with no traceback and no UnicodeEncodeError. Named reasons it
    stays partly met: Windows Terminal is installed but is a host window the driver cannot capture; macOS
    and Linux terminals are not on this machine; the legacy code-page checks were not run in PowerShell 7
    or Git Bash. Dumb terminal: `docs/ux/b054/` and `docs/ux/b054r/` are plain captures. Piped stdin:
    `docs/ux/b054r/J8-stdin.txt` (exit 0, `ract.result/1`). NO_COLOR: `tests/test_no_color.py`.
11. **Weak models still work: not met.**
    Sprint 6 evidence (`docs/ux/sprint6/80` and `docs/ux/sprint6/60`, the same ten journeys at both widths): the
    weak-model journey (J9) now names the cause and the next action: `Could not parse JSON plan from model response.
    The model hit its output limit (finish_reason=length)` and `hint: raise or remove max_tokens`. No file is changed.
    The row stays not met: no plan completes. The b054r captures use other scenario inputs, so the comparison is not
    like for like (see docs/ux/sprint6/README).
 The weak-model journey ends with
    `error: Planning failed: Plan contains no steps.` and no file changed
    (`docs/ux/b054r/J9.txt`). The JSON fallback did not complete a task.
12. **No internal chatter: partly met.** The provenance warning now reads in plain words:
    `provenance: N file(s) have no signature yet (files). See docs/PROVENANCE.md.`
    (`src/ract/session_turn.py`, `provenance_notice`; test in `tests/test_ux_gap_b.py`). It prints
    once per session (`src/ract/session_render.py`, `_on_notice`). The help text in
    `src/ract/cli.py:1695` still uses the project term (handoff below). Other diagnostics are not
    shown in these captures.
13. **Trust over a day (`/diff`, `/cost`, `/context`, `/permissions`): partly met.** `/cost`,
    `/context` and `/permissions` exist and fit at 40 and 60 columns (`src/ract/repl.py`, `_cmd_permissions`;
    `docs/ux/permissions/`; tests in `tests/test_ux_gap_b.py` and `tests/test_ux_width.py`). `/diff` does not
    exist as a command (handoff below).

## Journeys

- **J1 First run, empty directory: partly met.** The `Y` path asks four questions, writes the
  config and runs the health check, which names the missing server with a hint
  (`docs/ux/c_journeys/J1.txt`). A working prompt needs a model server, which this machine does not
  have. Under three minutes was not timed with a person at the keyboard.
- **J2 Daily start: partly met.** Model, branch and mode show, and the start screen names the last
  session with `/resume` (`docs/ux/c_journeys/J2.txt`). Context use is not on the status line
  (standard 6, handoff).
- **J3 Ask about the code (read-only): not run.** Not runnable: no read-tool scenario in the
  fake server (carried from B-054).
- **J4 Fix the failing test: not met.** The edit, diff and undo hint appear
  (`docs/ux/b054/J4.txt`), but the turn says `verified: RACT ran no tests this turn` and does
  not offer to run the test. The bar says "claims success without running tests" is a fail.
- **J5 Multi-file change with review: not met.** No per-hunk accept or reject (B-014c).
- **J6 Interrupt and queue: partly met.** Ctrl-C stops the turn and returns to the prompt
  (`docs/ux/b054r/J6.txt`; test at `tests/test_session_turn.py:209`). Queueing is not built.
- **J7 Resume and rewind: not met.** `/resume` lists and switches sessions. Esc Esc rewind is
  not built, so the rewind criterion fails. Not walked: a resume that restores the workspace.
- **J8 Headless in CI: met for the success path.** `ract -p ... --output-format json` returns
  `ract.result/1` with exit 0 (`docs/ux/b054r/J8.txt`); stdin piping works
  (`docs/ux/b054r/J8-stdin.txt`). A failing run's exit code is not captured.
- **J9 Weak local model: not met.** No file was written and no steps ran; the result is an
  unexplained empty plan with a hint (`docs/ux/b054r/J9.txt`), which fails the criterion.
- **J10 Failure paths: partly met.** Provider 503 gives cause and hint, and the workspace line
  says `no files were changed` (`docs/ux/soak_g/J10_cols80.txt`). The error sweep covers the other
  paths (`docs/ux/errors_check.md`): a missing key variable was not reproduced against the fake server,
  which does not check keys; a read-only directory cannot be made on Windows without an ACL deny; a
  budget stop was not run.

## Column checks (real terminal, final tip 71f6109)

Widest line per capture, in characters (`docs/ux/width_a/`, package A; `docs/ux/soak_g/` for the soak).
A capture fits when its widest RACT output line is at or under the column count.

| Command | 40 columns | 60 columns | Verdict |
|---|---|---|---|
| `/help` | 40 | 60 | met at both widths |
| `/sessions` | 35 | 57 | met at both widths (captured before package A; unchanged) |
| `/context` | 40 | 59 | met at both widths (captured before package A; unchanged) |
| `/cost` | 40 | 60 | met at both widths |
| `/mode` | 40 | 57 | met at both widths |
| `/settings` | 40 | 57 | met at both widths |
| `/model` | 37 | 57 | met at both widths |

Soak at 80 and 60 columns (`docs/ux/soak_g/`): every transcript fits its width, except the approval
question at 80 columns, which carries the heartbeat tick on the same line (the known B-033s
condition, handoff below).

## Soak (package G, final tip ebde7f3; code as 8296148, the last change is a test)

Time to first feedback in seconds, against the first run in `docs/ux/b054/timings.txt`. The first
number for J1 includes the setup probe in the first run and is not comparable.

| Journey | First run | Soak, 80 columns | Soak, 60 columns |
|---|---|---|---|
| J1 setup (`n` answer) | 7.11 (probe included) | 0.94 | 0.82 |
| J2 daily start | 2.86 | 1.13 | 1.05 |
| J4 fix a test | 2.12 | 1.01 | 0.90 |
| J6 interrupt | 2.13 | 1.00 | 0.97 |
| J8 headless, argv and stdin | exit 0, `ract.result/1` | exit 0 both | exit 0 both |
| J9 weak model | 1.53 | 0.91 | 1.15 |
| J10 failure paths | 2.31 | 0.90 | 1.02 |

J3, J5 and J7 are not runnable and are not in the soak.

## Summary for the release gate (B-051)

Standards: 0 met; partly met 2, 3, 4, 5, 6, 7, 8, 10, 12, 13; not met 1 (escalated), 9, 11.
Journeys: J8 met on the success path; J1, J2, J6, J10 partly met; J4, J5, J7, J9 not met; J3 not run.
Column checks: `/help`, `/cost`, `/mode`, `/settings`, `/model` fit at 40 and 60 after package A.
Open S1: D2 (queue indicator, B-033). Handoffs and ESCALATEs are listed below; the phase does not close.

## Package B (ux-gap): changes and handoffs

Changed in this package (lane: terminal output, renderer, REPL text, docs):
- Standard 8: a near-miss command gets `Did you mean /help?` (`src/ract/repl.py`).
- Standard 12: the provenance notice uses plain words and names the files (`src/ract/session_turn.py`).
- Package A, standard 10: `/help`, `/cost`, `/mode`, `/settings` and `/model` fit the width at 40 and 60
  (captures in `docs/ux/width_a/`; tests in `tests/test_ux_width.py`).

Handoffs (not changed here; the owner and the change are named):
- **Standard 1, heartbeat interval.** `src/ract/session_render.py:52`, `_PLAIN_HEARTBEAT_EVERY_MS = 10_000`,
  with the reason in the comment at lines 48 to 50. The bar asks for a sign of life every 2 s. The
  change is a decision on screen-reader noise: ESCALATE to the operator, default kept at 10 s in
  plain mode. The interactive status row (2 s) is not visible in the rich-mode captures
  (`docs/ux/b054r/J4.txt` shows 10 s ticks). Owner: BUILDER, the rich renderer.
- **Standard 1, heartbeat on the approval question.** Interim hold in place (adjudication row 5, `src/ract/question_gate.py`; captures `docs/ux/heartbeat_hold/`; tests `tests/test_heartbeat_hold.py` at 80, 60 and 40 columns). The permanent fix stays with B-033s. Condition: a tick fires while the
  `[y/N]` question is open. `docs/ux/b054r/J4.txt` line 8.
- **Standard 2, streaming and tool cards.** `src/ract/repl.py:96`, `stream: bool = False`. No collapsible
  reasoning, no one-line tool cards. Owner: BUILDER.
- **Standard 3, per-hunk accept and reject.** B-014c.
- **Standard 4, checkpoints listed.** `/undo` works (`src/ract/repl.py`, `_cmd_undo`); the list of checkpoints
  and what changed in each is not built. Owner: BUILDER (undo_backup).
- **Standard 5, queue ahead.** B-033.
- **Standard 6, context use, tokens, cost and session id on the status line.** The status line is
  `src/ract/session_render.py` `_on_session_started`. Context needs the provider probe (`context_limit` is
  null); session id is not in the event. Changing the event field is an ESCALATE. Owner: BUILDER.
- **Standard 9, approval choices.** `src/ract/approval_callback.py:35` offers `[y/N]` only. Owner: B-033s
  and the executor (approval policy).
- **Standard 11, weak models.** `src/ract/planner.py:34` returns `Plan contains no steps.` for a reply with no
  steps; the JSON fallback is a planner change. Senior-only (planner). ESCALATE.
- **Standard 13, `/diff`.** Not built; see the final handoffs. `/permissions` was added in package G.
- **Wording, `src/ract/cli.py:1695`.** `Provenance: files written by ract runs are not signed with a Rootknot`
  is help text in the project's own term. The integration test pins the run-output text at `cli.py:5147`
  (`tests/integration/test_unsigned_artifacts_are_reported.py:69`), so only the help text is in the handoff.
  Owner: BUILDER (cli).

## Package C (ux-gap): the journeys a user stops on

| Journey | First stop (captured) | Fixed in this package | Re-run (time to first feedback) | Status |
|---|---|---|---|---|
| J1 first run | `Set one up now? [Y/n]`, then four questions (memory, local or cloud, wait for server, git init). The health check says `nothing is answering at http://127.0.0.1:11434/v1 (connection refused)` with a hint (`docs/ux/c_journeys/J1.txt`). | none needed; the path works | 12.7 s, with no server on this machine | partly met: a working prompt needs a model server that this machine does not have |
| J2 daily start | `last session h-7f3a9c21d0e4 (...): fix the failing test ... /resume to continue it.` (`docs/ux/c_journeys/J2.txt`, line 2) | the resume offer (`src/ract/repl.py`, `_resume_offer`; tests in `tests/test_ux_gap_c.py`) | 4.08 s | partly met: no context use on the status line (handoff) |
| J4 fix the failing test | `verified: RACT ran no tests this turn`; nothing offers to run the named test (`docs/ux/b054r/J4.txt`, line 40) | none in lane | not re-run (model time of 88 s) | not met: handoff below |
| J5 multi-file review | no per-hunk accept or reject | none in lane | not run | not met: handoff below (B-014c) |
| J6 interrupt | `[!] 1. Fix add() ... failed` after Ctrl-C (before this package) | a step that fails after a stop was requested is shown as skipped (`src/ract/session_render.py`, `_stop_requested`; tests in `tests/test_ux_gap_c.py`) | 3.27 s | partly met: no queue indicator (B-033) |
| J9 weak model | `Planning failed: Plan contains no steps.` then `no question is waiting` on `y` (`docs/ux/c_journeys/J9.txt`) | the hint and the stray-answer line were fixed in package B's predecessors (B-054f) | 2.81 s | not met: the JSON fallback is a planner change (handoff below) |
| J10 failure paths | retries, `HTTP 503` with its message, `tokens not reported by the provider` (`docs/ux/c_journeys/J10.txt`) | none needed | 2.51 s | partly met: missing key, read-only disk and budget not run |

J3, J5 and J7 are not run. What each needs, and from which card:
- **J3 (ask about the code, read-only).** The model must read and search files itself. No read tool is wired into the `/ask` path. Owner: BUILDER (agent tool loop); no card number yet.
- **J5 (per-hunk accept or reject).** Owner: B-014c.
- **J7 (Esc Esc rewind).** Not built; `/resume` exists. Owner: BUILDER (rewind over `undo_backup`).

Handoffs added by package C:
- **J4, the named test is not run.** `src/ract/session_render.py` prints `verified: RACT ran no tests this turn` from the turn event. The verifier must run the test the intent names. Owner: BUILDER (verifier). The renderer change is ready once the event carries a verdict for that run.
- **J9, planner with no steps.** `src/ract/planner.py:34`. A JSON fallback for a weak model is a planner change. Senior-only. ESCALATE.
- **J2 and standard 6, context use on the status line.** Needs the provider probe; see the Package B handoff for standard 6.

## Final handoffs and ESCALATEs (package G)

Every partly met or not met line above has a named reason here or in the sections before. Owner and
file are given; the change is the one someone else would make.

Handoffs:
- **Standard 1, heartbeat on the approval question.** Interim hold in place (adjudication row 5, `src/ract/question_gate.py`; captures `docs/ux/heartbeat_hold/`; tests `tests/test_heartbeat_hold.py` at 80, 60 and 40 columns). The permanent fix stays with B-033s. `src/ract/session_render.py` and the
  approval prompt in `src/ract/approval_callback.py`. The tick is appended to the open `[y/N]`
  question (`docs/ux/soak_g/J4_cols80.txt`, `docs/ux/b054r/J4.txt` line 8).
- **Standard 2, streaming and tool cards.** BUILDER. `src/ract/repl.py`, the `stream` default (line
  near 96) and the reasoning display.
- **Standard 3, per-hunk accept and reject.** B-014c.
- **Standard 4, checkpoints listed.** BUILDER. `src/ract/undo_backup.py`: a list with what each holds.
- **Standard 5, queue ahead.** B-033. A typed-ahead intent is not announced: `docs/ux/c_journeys/queue_typed_ahead.txt`
  shows the second intent typed during a turn with no `queued` line.
- **Standard 6, context use, tokens, cost, session id on the status line.** BUILDER. Context needs the
  provider probe; the session id is not in `session.started`. Changing that event field is an ESCALATE.
- **Standard 9, approval choices.** B-033s and the executor. `src/ract/approval_callback.py:35` offers `[y/N]` only.
- **Standard 11, weak models.** Senior-only: `src/ract/planner.py:34` and the JSON fallback for a weak model.
- **Standard 12, internal wording.** `src/ract/cli.py:1695` (provenance help text), the LSP and
  semantic-builder lines printed by `ract memory init` (`docs/ux/cold_reader.md` row 5).
- **Standard 13, `/diff`.** BUILDER: a command that shows the last turn's diff from its backup (`undo_backup`).
- **Journey J4, the named test is not run.** BUILDER (the verifier). The renderer change is ready once
  the turn event carries a verdict for the test run.
- **Journey J5, per-hunk accept or reject.** B-014c. **Journey J3, read-only ask.** BUILDER: the
  agent tool loop; no read tool is wired into `/ask`. **Journey J7, Esc Esc rewind.** BUILDER (over
  `undo_backup`).
- **Error sweep rows 2, 4, 9, 10, 15, 21, 22.** `src/ract/cli.py` (argparse block, doctor and fence
  next actions, the approval-denied hint) and `src/ract/headless.py` (JSON errors). Owners: BUILDER.
  Row 14 (Ctrl-C at approval counted as a failed step): `src/ract/executor/steps.py`, the step's
  exception path (BUILDER).
- **Cold reader rows 3, 5, 6 and 7.** `src/ract/cli.py` (fence on a missing file, memory-init noise,
  the provenance sentence, the novelty budget hint). BUILDER.
- **The session guide's generator** is outside the repository (`scratchpad/build_guide.py`). Move it
  into the repository so the known-issues text is generated, not edited by hand (`docs/ux/cold_reader.md`).

ESCALATEs (default in force, operator decision needed):
- **Standard 1, heartbeat interval.** Plain mode prints a tick every 10 s by design
  (`src/ract/session_render.py:52`, `_PLAIN_HEARTBEAT_EVERY_MS`), for screen-reader noise. The bar asks
  2 s. Default: 10 s in plain mode; the 2 s status row belongs to the rich renderer, which the captures
  do not show. Operator decision.
- **Error sweep row 8, uncommitted changes.** Should RACT warn when a run starts in a git repository
  with uncommitted changes? Default: no warning in this release.
- **Session guide sample for two unsigned turns (D7).** A new scenario `plan_three_steps_twice.json`
  is needed for a two-completed-turn capture. Default: add it and re-capture; the D7 test stays.
- **Event placeholder `?` in `session.started`.** Changing the event field is an ESCALATE; the renderer
  reads `?` as "no model".

Look-again pass (operator direction of 19:15 PT): the standards still partly met were checked against
the code and the captures. Nothing else could move inside the lane without a change to the event
schema, the executor, the planner, the approval flow or the CLI verbs, so each one above names its owner
instead.
