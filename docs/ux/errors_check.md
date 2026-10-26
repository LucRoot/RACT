# Error sweep (ux-gap, package F)

Each row is a user-facing error triggered in a scratch directory or a real pty against the fake
server. The captures are in `docs/ux/errors/` (`errors_raw.txt`, `errors_raw2.txt`,
`errors_raw3.txt`, `errors_raw4.txt`).

The bar for a pass: one sentence on what happened, one next action, no category word, no raw
JSON, no traceback. Verdicts: **pass**, **partial** (the sentence is there, the next action or
the wording is not), **fail** (no sentence, or a wrong next action), **not reached** (the run
stopped at an earlier error; the reason is named), **not run** (cannot be reproduced here).

| # | Trigger | Command | Captured output (first lines) | Verdict | Fix or handoff |
|---|---|---|---|---|---|
| 1 | missing config | `ract run "add a greeting" --config ract.yaml` | `✗  failed: Configuration file not found: ract.yaml` / `hint: run ract setup here to create one` | pass | none |
| 2 | bad flag | `ract run --nope` | 17 lines of usage, then `ract: error: unrecognized arguments: --nope` | partial: the cause is last, under a usage block, with no next action | handoff: `src/ract/cli.py` argparse (BUILDER). Proposed: one line `unrecognized option --nope; run ract --help for the options` |
| 3 | unknown verb | `ract frobnicate` | treated as an intent: `Configuration file not found` | pass by design (a bare word is an intent) | none |
| 4 | empty intent | `ract run ""` | the hint line comes first, then the 17-line usage block, then `intent is required` | partial: the order is reversed and the usage block repeats the cause | handoff: `src/ract/cli.py` (BUILDER). Proposed: keep the hint, drop the usage block |
| 5 | missing key variable | `ract run ... --dry-run` with `api_key_env` unset | `note: this repository is not trusted ...` / `To allow them: ract trust` | pass for the trust gate; the key message is **not reached** (the trust gate stops first). After `ract trust` the fake server ignores keys, so the key message is **not reproduced** | none in lane. The key path needs a provider that checks keys |
| 6 | refused connection | `ract run ... --dry-run` with `url: http://127.0.0.1:9/v1` | `✗  failed: Provider call failed: Request failed: nothing is answering at http://127.0.0.1:9/v1 (connection refused).` / `hint: start your model server, or fix the provider url in ract.yaml` | pass | none |
| 7 | no git repository | `ract run ...` in a plain folder | `note: this directory is not a git repository; RACT writes directly into your files for this run` (seen in the cold reader, `docs/ux/cold_reader.md`) | pass (the note is seen when the run gets past planning; this run stopped earlier, so the capture is from the cold reader) | none |
| 8 | dirty working tree | `ract run ... --auto` in a git repository with an uncommitted change | no warning is needed: the step's tree is a snapshot of the working tree, so the uncommitted edits are in it (test `tests/test_uncommitted_edits_in_step_tree.py`, ADR-0047 D6). Files left out (too large, past the count, over the time budget) already print a notice at run start (`src/ract/executor/substrate_adapter.py:258`). Adjudicated 2026-10-26, row 2 | pass (closed by evidence) | none |
| 9 | binary file, doctor | `ract doctor` in a folder with a binary file and no config | `FAIL config_exists: Configuration file not found: ract.yaml` with no next action; then `Provenance: ... not signed with a Rootknot` | partial: no hint; the provenance line uses the project's term | handoff: `src/ract/cli.py` doctor (BUILDER). Proposed: `run ract setup here to create one`; the provenance sentence as in the session notice |
| 10 | large file, fence | `ract fence inspect --file logo.bin` (and a 9 MB file) | `[ract] config not found: ract.yaml` with no next action | partial | handoff: `src/ract/cli.py` fence verb (BUILDER): name the next action, as in row 1 |
| 10b | large file in a turn's diff | a 9 MB file changed by a step | **not reached**: the run needs the changed file in the plan; not run in this sweep | not run | `src/ract/session_render.py` already caps the diff at 8 MiB (`_MAX_DIFF_BYTES`); the notice text was not checked |
| 11 | read-only directory | a folder that refuses writes | **not run**: on Windows the read-only attribute does not stop file creation; an ACL deny is needed | not run | none |
| 12 | Ctrl-C at the REPL prompt, text typed | `ract`, type `half a sentence`, Ctrl-C | the typed text is dropped and the prompt returns (`docs/ux/errors/errors_raw4.txt`) | pass | none |
| 13 | Ctrl-C during a turn | a model call in flight | `stopping...` then `Stopped. The model call is still finishing in the background; nothing it returns will be written.` | pass | none (J6) |
| 14 | Ctrl-C at the approval prompt | default mode, a step asks `[y/N]`, Ctrl-C | `[!] 1. Fix add() ... (8.1s) failed`, then `stopping...` (`errors_raw3.txt`). The matrix (package H) also showed the next output printed onto the question's line. | partly met: the newline after the Ctrl-C is now printed and the question folds to leave room for the answer (`src/ract/approval_callback.py`; `tests/test_approval_prompt_fit.py`, commit 6795d9f). The step is still labelled `failed` when the cause was the operator's Ctrl-C: the executor records the worker's exception as a failed step (`src/ract/executor/steps.py`, BUILDER; adjudication row 6) | BUILDER handoff |
| 15 | Ctrl-C at the setup prompt | `ract` in an empty folder, Ctrl-C at `Set one up now? [Y/n]` | nothing is printed after the prompt; the process ends | fail: no line says that no config was written | handoff: setup flow in `src/ract/cli.py` (BUILDER). Proposed: `Setup stopped; no ract.yaml was written.` |
| 16 | unknown slash command | REPL `/zzqxwv` | `✗  unknown command /zzqxwv. Type /help for the list.` | pass | none (package B gives a nearest command when one exists) |
| 17 | `/resume` with no id | REPL `/resume` | `usage: /resume <id|latest>. /sessions lists the saved ids.` | pass (after the fix in this package; the usage alone did not say where ids are) | `src/ract/repl.py` `_cmd_resume`; test `test_resume_without_an_id_names_the_way_to_find_one` |
| 18 | `/resume latest` with no sessions | REPL `/resume latest` | `no sessions yet` (captured in `errors_raw5.txt`); no next action in the first capture | pass after the fix: `no sessions yet: a request you type starts one` (`src/ract/repl.py`; test `test_no_sessions_says_how_one_starts`) | none |
| 19 | unknown model name | REPL `/model nosuch` | `✗  no provider named 'nosuch'. valid names: local` | pass | none |
| 20 | empty intent in the REPL | an empty line | nothing happens, the prompt returns | pass | none |
| 21 | headless, no config | `ract -p "add a greeting" --output-format json` | `error: configuration file not found: ract.yaml. hint: run ract setup --answers FILE here (template: ract setup --print-defaults)` | partial: the hint is good, but the output is plain text although `--output-format json` was asked for | handoff: `src/ract/headless.py` (BUILDER): an error in JSON mode should be the result object, to check against `ract.result/1` |
| 22 | approval denied, no terminal | `ract run ... --auto` with no terminal to answer | `✗  failed: Approval denied for step 1: ...` then `hint: run ract doctor --check-providers to check the setup` | fail: the hint names the provider check, which is not the cause. The session's own hint for this case says `pass --accept-edits` | handoff: the CLI's hint mapping in `src/ract/cli.py` (BUILDER): an approval denial gets the `--accept-edits` hint |

## Summary

- Pass: rows 1, 3, 6, 7, 12, 13, 16, 17, 18, 19, 20 (row 3 by design; rows 17 and 18 after the fixes).
- Partial: rows 2, 4, 9, 10, 14, 21.
- Fail: rows 15, 22.
- Not reached or not run: rows 5 (key path), 10b, 11.
- Row 8 (dirty tree): closed by evidence in adjudication row 2 (no warning needed).

## Handoffs (owner and change)

- `src/ract/cli.py` argparse: rows 2 and 4 (one line and a hint in place of the usage block).
- `src/ract/cli.py` doctor and fence: rows 9 and 10 (a next action when no config is found).
- `src/ract/cli.py` setup: row 15 (`Setup stopped; no ract.yaml was written.`).
- `src/ract/cli.py` hint mapping: row 22 (approval denied gets the `--accept-edits` hint).
- `src/ract/executor/steps.py`, step exception path: row 14 (a Ctrl-C at approval ends a step as stopped).
- `src/ract/headless.py`: row 21 (JSON errors as the result object).

- `src/ract/headless.py`, `run_headless`, the `_read_stdin(stdin or sys.stdin)` call (line near 271), B-035
  (adjudication row 16). With an intent on the command line and stdin inherited from a parent that
  never closes it, `ract -p "<intent>"` hung for 90 s in two trials (scratchpad probe, 2026-10-26); the
  read happens before the intent is checked. Proposed change: read stdin only when the intent is empty, or
  only when stdin is a pipe that has data, and keep the "both" case labelled as context. Pinned as an
  expected failure in `tests/test_headless_stdin_with_intent.py`. The no-intent case returns
  `error: no prompt` at once, so it is not a hang.

## Decision for the operator (ESCALATE)

- Row 8: should RACT warn when a run starts in a git repository with uncommitted changes?
  Default: no warning in this release; the existing note stays. Not changed.
