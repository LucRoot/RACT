# UX bar check (B-054 sweep, integ-check 994bb6f)

One line per numbered item in `BOARD/UX_BAR.md`: standards 1 to 13 and journeys J1 to J10.
Each status is backed by a capture or a test, named on the line. Where neither exists,
the status says so. Evidence paths are relative to this worktree.

Status words: **met**, **partly met**, **not met**. "Not run" means the journey could not be
walked in this batch, with the reason.

## Standards

1. **Feedback within 300 ms, sign of life every 2 s: not met.** The plain renderer prints the
   heartbeat every 10 s (`src/ract/session_render.py:52`, `_PLAIN_HEARTBEAT_EVERY_MS = 10_000`).
   Captures show `... waiting on model (4 s)` then steps of 10 s
   (`docs/ux/b054r/J4.txt`). No feedback is measured at submit; the 300 ms figure is not checked.
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
6. **Know where you are (model, provider, branch, context, tokens, cost, mode, tier, session id):
   partly met.** The status line shows model, provider, branch, mode and tier
   (`src/ract/session_render.py:158`; `docs/ux/b054r/J2.txt` line 2). Context use, tokens, cost
   and session id are not on it. `/cost` and `/context` carry those in separate screens.
7. **Errors say what to do (hint line, no traceback): partly met.** Hints are tested for each
   error class (`tests/test_session_turn.py:188`, `test_every_error_gets_a_hint`). Captures show
   a `hint:` line (`docs/ux/b054r/J9.txt`, `docs/ux/b054r/J10.txt`). No traceback appears in any
   capture of this batch. Not checked: unhandled exceptions outside the hinted paths.
8. **No dead ends (nearest command, setup flow, refusal explains how to permit): partly met.**
   `/resume` suggests the closest session id (`src/ract/session_listing.py:98`, `closest_id`).
   An unknown command now suggests the nearest one: `unknown command /hlep. Did you mean /help?`
   (`src/ract/repl.py`, `_handle_command`; tests in `tests/test_ux_gap_b.py`). The setup
   flow asks a question (`docs/ux/b054r/J1.txt` line 2) but was not run past the `n` answer.
9. **Permissions are understandable (exact change, reason, four choices): not met.** The
   approval prompt offers `[y/N]` only (`src/ract/approval_callback.py:34`). No allow-once,
   allow-for-session, allow-always or prefix choice exists.
10. **Works where users work (80 columns, dumb terminal, piped stdin, NO_COLOR): partly met.**
    Captures at 40 and 60 columns of five commands are in `docs/ux/ux_bar/` (see the table
    below). Dumb terminal: `docs/ux/b054/` and `docs/ux/b054r/` are plain captures. Piped
    stdin: `docs/ux/b054r/J8-stdin.txt` (exit 0, `ract.result/1`). NO_COLOR: `tests/test_no_color.py`.
    Windows Terminal, macOS and Linux terminals were not run. `/help` overflows at 40 and 60
    columns (see the table).
11. **Weak models still work: not met.** The weak-model journey ends with
    `error: Planning failed: Plan contains no steps.` and no file changed
    (`docs/ux/b054r/J9.txt`). The JSON fallback did not complete a task.
12. **No internal chatter: partly met.** The provenance warning now reads in plain words:
    `provenance: N file(s) have no signature yet (files). See docs/PROVENANCE.md.`
    (`src/ract/session_turn.py`, `provenance_notice`; test in `tests/test_ux_gap_b.py`). It prints
    once per session (`src/ract/session_render.py`, `_on_notice`). The help text in
    `src/ract/cli.py:1681` still uses the project term (handoff below). Other diagnostics are not
    shown in these captures.
13. **Trust over a day (`/diff`, `/cost`, `/context`, `/permissions`): partly met.** `/cost` and
    `/context` exist (`src/ract/repl.py:415` and `:615`). `/diff` and `/permissions` do not exist
    as commands; `/help` does not list them.

## Journeys

- **J1 First run, empty directory: not met.** The `n` path ends with `ract.yaml not found`
  and no config (`docs/ux/b054r/J1.txt`). The setup flow (`Y` path) was not walked, so the
  under-3-minutes and working-config criteria are not checked.
- **J2 Daily start: partly met.** Model, branch and mode show (`docs/ux/b054r/J2.txt`). Context
  use and the resume offer do not appear (J2 starts with `no sessions yet`).
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
  says `no files were changed` (`docs/ux/b054r/J10.txt`). Provider key missing, read-only disk
  and budget exhaustion were not run.

## Column checks (real terminal, `docs/ux/ux_bar/`)

Widest line per capture, from `docs/ux/ux_bar/widths.txt`. A capture fits when its widest
line is at or under the column count. The check is on the RACT output lines.

| Command | 40 columns | 60 columns | Verdict |
|---|---|---|---|
| `/help` | 80 (table is fixed at 80) | 80 | **not met** at both widths |
| `/sessions` | 35 | 57 | met at both widths |
| `/context` | 40 | 59 | met at both widths |
| `/cost` | 80 (the `ledger:` path line) | 80 | **not met** at both widths |
| `/mode` | 55 (`default: RACT asks before each step that changes a file`) | 57 | **not met** at 40; met at 60 |

Evidence: `docs/ux/ux_bar/cols40_help.txt`, `cols60_help.txt`, `cols40_cost.txt`,
`cols60_cost.txt`, `cols40_mode.txt`, `cols60_mode.txt`, and the sessions and context captures.

## Summary for the release gate (B-051)

Standards: 0 met, 10 partly met (2, 3, 4, 5, 6, 7, 8, 10, 12, 13), 3 not met (1, 9, 11).
Journeys: 1 met (J8, success path), 3 partly met (J2, J6, J10), 5 not met (J1, J4, J5, J7, J9),
1 not run (J3). Column checks: `/sessions` and `/context` fit at 40 and 60; `/help` and `/cost`
do not fit at either width; `/mode` does not fit at 40. Open S1 defect: D2 (queue and Ctrl-C
indicator, B-033), which waits for the BUILDER. The phase does not close.

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
- **Standard 1, heartbeat on the approval question.** B-033s. Condition: a tick fires while the
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
- **Standard 9, approval choices.** `src/ract/approval_callback.py:34` offers `[y/N]` only. Owner: B-033s
  and the executor (approval policy).
- **Standard 11, weak models.** `src/ract/planner.py:34` returns `Plan contains no steps.` for a reply with no
  steps; the JSON fallback is a planner change. Senior-only (planner). ESCALATE.
- **Standard 13, `/diff` and `/permissions`.** Neither command exists. Owner: BUILDER (new commands).
- **Wording, `src/ract/cli.py:1681`.** `Provenance: files written by ract runs are not signed with a Rootknot`
  is help text in the project's own term. The integration test pins the run-output text at `cli.py:5085`
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
