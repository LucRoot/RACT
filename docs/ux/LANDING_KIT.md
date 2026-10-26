# Landing kit (MASON, sprint 5, package N)

Read this first. The BUILDER lands one branch in one pass: `work/mason/landing`.

## The branch to land

- **Landing branch:** `work/mason/landing`, tip **`79cf45f`**: the 49 commits of the first landing tip (`01b3cf0`) plus the 25 commits of `7097054..work/mason/ux-more` (no merges), replayed in order. **74 commits** on base `35af968`.
- **Current work tip:** `work/mason/ux-more` (this file's commit is the tip; it differs from the landing tip only in this file). **82 commits** on base `35af968`.
- **Base:** the feature tip `35af968` (`feat/interactive-session-and-setup-fixes`). Not checked out in the main checkout.
- **Tree check (`git diff --stat 79cf45f work/mason/ux-more`):** the replayed tree was identical to ux-more before this commit (empty diff, logged at 11:58 PT). This commit adds only `docs/ux/LANDING_KIT.md`.
- **Known noise, not content:** under `core.autocrlf=true` the `docs/ux/terminal_matrix/*.raw.txt` captures show as modified on checkout (CRLF in the working copy, LF in the commit). Do not commit those files from a checkout.

### Gate on the landing tip `79cf45f` (run 2026-10-26, 11:58 to 12:35 PT)

- **Set:** the whole `tests/` tree (378 files). It is a superset of the set that produced 543 passed on the first landing tip, which is the architecture tests, the release-surface set and the sprint 5 test files. The exact command behind the 543 count is not recorded in the board; the whole-tree run is the safe superset.
- **Result:** **5088 passed, 43 skipped, 1 xfailed, 8 failed**, exit 1 (2210 s).
- **Architecture tests** (`tests/architecture`): no failures.
- **`ruff check src tests`:** all checks passed.
- **`ruff format --check src tests`:** 7 files would be reformatted (956 already formatted): `tests/test_width_properties.py`, `tests/test_windows_file_hints.py` and five others. This gate is not clean.
- **The 8 failures** (all on the landing tree, which is the same content as ux-more):
  1. `tests/test_compression_novelty_detector.py::test_executor_routes_low_novelty_to_handshake_queue`: `FakeHandshakeRegistry` has no `project_dir`. Not my lane.
  2. `tests/test_dead_code_auction.py::test_ract_auction_reports_zero_dead_modules`: flags `cli_examples.py` (package S), and the prepared, unwired `ui/plan_approval_view.py` and `ui/queue_view.py` (packages J and K). My files; the prepared modules are unwired by design.
  3. `tests/test_egress_ledger.py::test_cost_in_the_session_shows_only_this_session`: depends on the temp path. Not my lane.
  4. `tests/test_modes.py::test_default_mode_asks_before_the_change_in_a_real_session[y-True]` and `[n-False]`: both assert False. Not my lane.
  5. `tests/test_release_surface.py::test_rebuild_signals_all_green[R10-...]`: README is over 500 words (excluding code blocks).
  6. `tests/test_release_surface.py::test_no_closed_ip_terms_in_tracked_files`: the term `rootclaw` appears in four tracked files, all mine: `docs/ux/terminal_matrix/conpty_direct_ctrl_c.raw.txt`, `conpty_direct_journey.raw.txt`, `conpty_direct_paste.raw.txt` and `docs/ux/windows_files/results.json`. The hits are machine paths in captures (a rule breach: no machine paths in tracked files). Fix: scrub the paths in those captures.
  7. `tests/unit/test_intent_recompile_cli.py::test_cli_intent_verb_exists`: did not raise `SystemExit`. Not my lane.

## Operator-directed change: GLM-5.3 preset (supersedes D-036)

- Commit `56fa5d0` on ux-more (landing tip includes it). The Moonshot preset is removed, because `api.moonshot.cn` is not funded. The `glm` preset uses `https://integrate.api.nvidia.com/v1`, `${NVIDIA_API_KEY}` and `z-ai/glm-5.3`, as the Endpoints Skill names it (the `code` function).
- **Supersedes D-036** ("Moonshot preset: keep"), by operator direction on 2026-10-26.
- **Tested column: configuration checked only.** No request has been sent to this endpoint from RACT.
- K3 (Kimi) reached end of life on 2026-10-15 and is not served on NIM (ENDPOINTS_SKILL.md); no K3 reference remains in RACT.

## The commits, in landing order (the 01b3cf0 landing branch, 49 commits)

Each row is one commit on `work/mason/landing`. Source branch in brackets.

| # | Landing hash | Source | One sentence |
|---|---|---|---|
| 1 | fe6986c | B-053b (3a00f12) | `ract.result/1` carries the plan as an array of step states. |
| 2 | 3b2986d | B-041c | The session renderer fits the terminal width, 40 to 80 columns. |
| 3 | 6f5f76a | B-041c | Long renderer lines and the approval question wrap to the width (partial). |
| 4 | 9d2acc9 | B-041c | The banner and the config warning wrap to the terminal width (partial). |
| 5 | 8c0be7b | B-041c (d7fa898) | Line wrapping is opt-in; only the REPL wraps to the terminal. |
| 6 | 7342c08 | B-054f (9421bad) | Walkthrough defects D1, D3 to D5, D7 to D11 fixed (wording, skipped steps, stray answers). |
| 7 | fcdf653 | B-054f (e48ba22) | Re-lock of the source digest for the walkthrough fixes. |
| 8 | 97c95e4 | B-048 (7f5e5f9) | First batch of the session guide, every sample from a capture. |
| 9 | bebe965 | B-048 (224e118) | The guide covers `/sessions` and `/resume`. |
| 10 | 427ba12 | B-048 (c4220a3) | The guide covers `/mode`, `/cost`, `/undo` and `/ask`. |
| 11 | ec8396d | B-048 (d315b26) | The guide covers `/context`. |
| 12 | 749e5a0 | B-048 (b606b47) | The guide shows a question that completes, marked as the fake server's answer. |
| 13 | dc4de2a | B-054 (2193847) | The ten-journey walkthrough, transcripts and defect list. |
| 14 | 0a1babc | B-054 (0e0d14b) | J1 re-run with the setup prompt answered `n`; D10 and D11 logged. |
| 15 | 38cd886 | B-054f (e2a0474) | The session line reads `?` as no model set (renderer side). |
| 16 | 361ea9a | B-054r (b4b9a84) | Walkthrough re-run on the merged tip, transcripts and defect list. |
| 17 | 355c2a5 | B-054 UX sweep (31085cd) | One line per standard and journey, column checks at 40 and 60. |
| 18 | 61b4494 | UX A | The REPL's multi-line commands fit the terminal width. |
| 19 | bc2d5c0 | UX B | Nearest-command suggestion (standard 8) and the plain provenance notice (standard 12). |
| 20 | 787e35a | UX C | A stopped step is skipped; the start screen offers the last session. |
| 21 | 6679ddb | UX D | Red-first evidence for D4 and D8; two-turn D7 capture; width captures. |
| 22 | f8617f9 | UX E | Cold-reader pass: README examples match a fresh project; resume offer punctuation. |
| 23 | 769e3e4 | UX F | Error sweep: stop announced before cancel; `/resume` and empty-session wording. |
| 24 | 00f0189 | UX F | The no-sessions line wraps to the terminal width. |
| 25 | 0785c19 | UX soak | The setup question fits 60 columns; Ctrl-C at it says no config was written. |
| 26 | 4def368 | UX G | Soak on the final tip and the final sweep file. |
| 27 | 6602972 | UX G | `/permissions`: one screen of what RACT may change or send. |
| 28 | 01bc276 | UX G | `/permissions` joins the width test at 60 and 40 columns. |
| 29 | ee458d3 | UX G | Soak numbers in the sweep file. |
| 30 | 0a17073 | Adjudication row 3 | `plan_three_steps_twice` fixture and the two-turn D7 capture. |
| 31 | b7c9bfe | Adjudication row 1 | Standard 1 states the plain-mode check as at most every 10 s. |
| 32 | dc92e2f | Adjudication row 2 | A step's tree contains uncommitted edits; test pins it; no warning added. |
| 33 | d1b8b6f | Adjudication row 4 | `ask_calc_answer` scenario; the guide's question section re-captured. |
| 34 | c91adb7 | Adjudication row 5 | Interim hold on heartbeat lines while an approval question is open. |
| 35 | a0435ed | Adjudication row 5 | The sweep file records the interim hold. |
| 36 | 301a5c1 | Adjudication row 16 | The stdin hang with an intent on the command line is pinned (strict xfail) and handed off. |
| 37 | a5e180c | UX I | Every renderer line is sanitized; an escape byte never reaches the terminal. |
| 38 | 3cedeb4 | UX I | The renderer wraps by terminal columns, not characters (`src/ract/cell_wrap.py`). |
| 39 | 231c557 | UX I | The hanging-indent property uses the wrap's own indent limit. |
| 40 | 842154a | UX I | The REPL's wrapped print and the approval question wrap by terminal columns. |
| 41 | faff6a9 | UX J | The queue view as pure data and text (`src/ract/ui/queue_view.py`), PREPARED and unwired. |
| 42 | e7cf51c | UX K | The plan approval screen, answers and data (`src/ract/ui/plan_approval_view.py`), PREPARED and unwired. |
| 43 | 332fa59 | UX H | The approval prompt leaves room for the answer; Ctrl-C ends its line. |
| 44 | fdaef7d | UX H | The `plan_unicode` scenario for the code-page runs. |
| 45 | ddc53bd | UX H | Terminal matrix: console by feature, with the captures and the findings. |
| 46 | 39e4620 | UX K | `plan_hash` uses the canonical encoding (`ract.canonical.dumps_jcs`). |
| 47 | b66f3d7 | UX L | Startup and latency measured; handoffs carry the measured savings. |
| 48 | b08bde8 | UX H look-again | Standards 5 and 10 cite the matrix and the prepared queue view. |
| 49 | 01b3cf0 | UX H look-again | Error row 15 passes after the setup fix; row 23 records the duplication-guard message. |

## Conflicts met while building the branch

- **Rebuild of 2026-10-26 (25 commits, `7097054..ux-more`, no merges):** the digest did not conflict. One conflict, in `docs/ux/LANDING_KIT.md` (a kit update), resolved by taking the ux-more version. The earlier false conflict (`3ab850d` in `repl.py` and `tests/test_render_width.py`) came from replaying the wrong set (the `git cherry` list); with the `git rev-list` set it does not occur.
- `src/ract/source_digest.py`: generated. The tree equals ux-more, so the lock on the landing tip is the lock on ux-more. The architecture tests pass on it.

## Branches of mine that are not in the landing branch

- **Already in the feature tip by patch content:** `work/mason/B-014b` (e7a8da1), `work/mason/B-076` (e7647e6), `work/mason/B-076-env` (8ecb557). No action.
- **Older READY branches, features present in the landing tree, commits not replayed:** `work/mason/B-014a` (ccf9ff4), `work/mason/B-014b-fixes` (8049f01), `work/mason/B-032a` (3490a60), `work/mason/B-032b` (366b1d0), `work/mason/B-041a` (86e9174), `work/mason/B-041b` (e5bd4ad), `work/mason/B-053a` (6e39b3a). Their test files exist in the landing tree and pass on its tip (`tests/test_diff_render.py`, `tests/test_summary_diff.py`, `tests/test_turn_diff_wiring.py`, `tests/test_context_command.py`, `tests/test_session_commands.py`, `tests/test_no_color.py`, `tests/test_plain_mode.py`, `tests/test_session_render_checklist.py`). Replaying their old commits would overwrite newer code. **ESCALATE** (default: not replayed; the BUILDER may land them history-only if the team wants the commits on the record).
- **Throwaway:** `work/mason/integ-check` (31085cd). Not to land.
- **Constituents of the landing branch, for reference:** `work/mason/B-053b` 3a00f12, `work/mason/B-041c` d7fa898, `work/mason/B-048` b606b47, `work/mason/B-054` 0e0d14b, `work/mason/B-054f` e2a0474, `work/mason/ux-gap` 492beef, `work/mason/ux-next` b0b3f1c, `work/mason/ux-more` b0b3f1c.

## Handoffs from package T (Windows file edge cases), by severity

Ordered so that the handoffs which print success that did not happen come first (H1 and H4). Full table and reasoning: `docs/ux/windows_files.md`.

1. **H1. A path over 260 characters reports done and writes nothing.** `src/ract/executor/steps.py` line 1136 (`"outcome": "done"`). No path-length check in `src/ract/workspace_path.py` `_string_checks` (line 130 onward). Fix: refuse over-long paths there, so the outcome is `refused` and the exit code is 3.
2. **H4. "done" is printed before a refusal to change a file.** `src/ract/executor/steps.py` line 1136 (the step is reported before the apply result) and `src/ract/executor/substrate_adapter.py` line 455 (`left these paths as they are`). Fix: report the step after the apply result is known; a skipped path prints as skipped.
3. **H2. A trailing space is removed silently and the file is written under the name without it.** `src/ract/workspace_path.py` line 130 (`raw.strip()`) runs before the check at line 175 (`seg != seg.rstrip(" .")`), so the check never sees the space. Fix: check `raw` before stripping, and refuse.
4. **H5. A case-variant name is reported as the planned case.** The changed-files line comes from the plan's name (`src/ract/executor/steps.py` near line 1136, `expected_artifact`), so `README.md` is reported as `Readme.md`. Fix: report the case the file system returns.
5. **H7. The headless path prints a full traceback for a locked file.** `src/ract/harness_report_enricher.py` line 56 (`logger.exception("Harness execution failed: %s", exc)`). The error is returned correctly; the logger writes the traceback. Fix: `logger.error` without exc_info, or debug level only. The REPL path is already fixed in `src/ract/repl.py` (`work()`).
6. **H6. The snapshot failure is raised as a generic error.** `src/ract/executor/worktree.py` line 740 (`could not snapshot the working tree`, from `git add`) is raised through `take_snapshot` and called unguarded from `src/ract/executor/substrate_adapter.py` line 253. Fix: fail the step as `failed` with a clean error from the substrate.
7. **H3. A byte order mark is dropped on a full rewrite.** The step's content replaces the file; the reads in `src/ract/executor/steps.py` lines 377, 395, 898 and 919 are `utf-8`. Decision needed: keep the BOM, or document that a full rewrite sets the encoding.

## Earlier BUILDER handoffs (sprints 4 and 5)

These are the defects found by MASON that the branch does not fix. Each names where the fix goes. These line numbers are as recorded in sprints 4 and 5 and were not re-checked on `56fa5d0`; H1 to H7 above were.

1. **Ctrl-C at the approval prompt is recorded as a failed step.** `src/ract/executor/steps.py` line 1091 (`error = result.error or "the step did not finish"`) and the step's exception path. The renderer already shows a stopped step as skipped when the stop comes first. Test to add: a Ctrl-C at an approval prompt resets the step to skipped.
2. **Duplication guard: the message and the hint.** `src/ract/executor/steps.py` line 1481 (`error=f"Duplication guard blocked write: {summary}"`), `src/ract/duplication_guard.py` line 28 (the wording), and `hint="duplication"` at `steps.py` line 1484. The category word is dropped by `_advice` (B-062), so the user gets the provider-check hint. Proposed wording is in package R of sprint 5 (`docs/ux/errors_check.md`, row 23).
3. **Headless reads stdin before the intent check.** `src/ract/headless.py` line 271 (`prompt = build_prompt(words or None, _read_stdin(stdin or sys.stdin))`). With an intent on the command line and an inherited stdin that never closes, the run hangs. Pinned as a strict xfail in `tests/test_headless_stdin_with_intent.py`. Owner: B-035.
4. **Planner returns no steps.** `src/ract/planner.py` line 34 (`error="Plan contains no steps."`). A weak model needs a JSON fallback. Senior-only.
5. **Approval denied at end of input gets the provider-check hint.** `src/ract/executor/steps.py` line 1190 (`Approval denied for step`). The hint should say to approve, or to pass `--accept-edits`.
6. **Provenance help text uses the project term.** `src/ract/cli.py` line 1691 (`Provenance: files written by ract runs are not signed with a Rootknot`). The run-output text is pinned by `tests/integration/test_unsigned_artifacts_are_reported.py`.
7. **`[ract] config not found` with no next action** on several verbs: `src/ract/cli.py` lines 521, 645, 1928, 2410, 2503 (fence, doctor and others). Proposed: `run ract setup here to create one`.
8. **The top-level parser prints a 17-line usage block for a bad flag.** `src/ract/cli.py`, `main` (line 4402) and the parser it builds. Proposed: one line and `run ract --help`.
9. **`session.started` sends `?` as the model and provider placeholder.** `src/ract/repl.py` line 835 (`model, provider = "?", "?"`). The renderer reads `?` as no model set (sprint 3, row 8). The BUILDER fills the values in the event; the renderer workaround is removed in the same commit.
10. **Memory init prints LSP and semantic-builder noise on a fresh project.** `src/ract/memory/lsp.py` line 263 (the `LspClient.references_of: LSP call failed` line) and the `semantic_builder` embed message. Owner: BUILDER (memory).
11. **Verifier does not run the test a request names (D6).** Inside B-023 (`run_tests`). Acceptance line: a request that names a failing test ends with the test run or an explicit "not run, because ...".
12. **`/diff` is not a command (standard 13).** BUILDER.
13. **Queue indicator, Ctrl-C queueing and the input owner (D2, standard 5).** B-033s, then B-033a and B-033b wire `src/ract/ui/queue_view.py` (prepared, unwired).
14. **Plan approval screen wiring.** B-064b wires `src/ract/ui/plan_approval_view.py` (prepared, unwired). The differences from ADR-0049 D12 are in `docs/ux/plan_approval_shape.md`.
15. **`input.withdrawn` event fields.** Proposed in the sprint 4 log; not emitted. Owner: BUILDER (B-033s design).
16. **Approval answer `no` cancels the whole plan.** `src/ract/ui/plan_approval_view.py`, `_CANCEL` set. A reviewer may want it removed (ESCALATE in the sprint 4 log).

## What the BUILDER does, in order

1. Decide the conflict in `src/ract/repl.py` and `tests/test_render_width.py` (commit `3ab850d`), then rebuild the landing branch from `35af968` with the 27 missing commits. `git fetch` is not needed; the branch is local.
2. Land `work/mason/landing` as one branch.
3. Run `ract source-digest --lock` on the result and commit the lock if it changed.
4. Read the handoffs above; the MANAGER turns them into cards.
