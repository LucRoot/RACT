# S2 on a real hosted model: first sprint report

Status: partial. One hosted model leg was run. The local 7B-class leg is not run, because no local endpoint has been named. S2 is not met by this report.

## Scope and code under test

- Provider and model: the hosted provider service, a large hosted model (its structurer role), through the `openai_compatible` adapter at `[hosted endpoint, held on the operator board]`. The model's name is withheld from tracked evidence: the repository's closed-terms release check (`tests/test_release_surface.py`) rejects it. The name is recorded in the operator's board.
- The repository has no provider preset. The scratch `ract.yaml` carries the URL and model above and reads the key from the environment (`api_key: ${PROVIDER_API_KEY}`). A preset is a change to key handling, which is senior-only, so none was added.
- Code under test: `work/mason/integrated` at `e2cb4b6`, exported read-only. It is not landed (the BUILDER's log has only a "to review" entry for it). The feature tip on this branch's base is `35af968`.
- Date of the runs: 2026-10-28, between 12:08 and 12:35 PDT.
- Key handling: the key was loaded into the environment of each RACT process and never written to a file, a capture or this report. Each capture was scanned for the key prefix and the first eight characters of the key before commit: no hits.

## Probe (`ract doctor --check-providers`)

| Fact | Result | Capture |
|---|---|---|
| Chat | works (1.1 s) | `captures/probe_doctor.txt` |
| Streaming | works (one text piece) | same |
| Tool calling | failed: no answer within 15 s | same |
| Reasoning text | returned | same |
| Context window | unknown (the server does not say) | same |

The docs' "configuration checked only" entries stay as they are. This preset is not in the table, so no table row changes.

Defect in the probe's advice: the advice estimates the model's memory needs against this machine (63 GB total, 9 GB free). That estimate does not apply to a remote endpoint. Severity S3, owner WRIGHT (`doctor_advice.py`).

Defect in the probe's classification: a tool-calling request that gets no answer within 15 s is reported as "failed". It is a timeout, which is closer to "unknown". Severity S3, owner WRIGHT (`capability_probe.py`).

## Task by run

Verdict is the harness's: what RACT printed and its exit code. Tokens are the ledger's counts for the whole endpoint, shown in the total below, because the ledger does not split tokens per run. "First feedback" was not measured: the captures carry no timestamps.

| Task | Run | Result | Harness verdict | Wall time | Defect |
|---|---|---|---|---|---|
| (a) one-file change | 1 | refused: reply not a valid python file; nothing written | failed (refusal) | 16 s | D3 |
| (a) one-file change | 2 (stream) | refused, same reason | failed (refusal) | 19 s | D3 |
| (a) one-file change | 3 (stream) | src/calc.py fixed; 2 tests pass | done | 75 s | none |
| (a) one-file change | 4 (stream) | refused, same reason | failed (refusal) | 23 s | D3 |
| (b) three-step change | 1 | all three files written; notes.py invalid | done | 28 s | D1, D2, D3 |
| (b) three-step change | 2 | same as run 1 | done | 37 s | D1, D2, D3 |
| (b) three-step change | 3 | same as run 1 | done | 35 s | D1, D2, D3 |
| (c) make a failing test pass | 1 | src/calc.py fixed; 2 tests pass | done | 13 s | none |
| (d) approval refused halfway | 1 (default mode, no flag, real terminal) | no approval prompt; all three files written | done | 98 s | D4 |
| (d) approval refused halfway | 2 (`--auto`, real terminal) | prompt for step 1: yes; step 2: no; run stopped | failed (approval denied) | about 70 s to the refusal | D9 |
| (e) long reply | 1 | refused by the duplication guard (similarity 1.000) | failed (refusal) | 39 s | none (correct refusal) |
| (e) long reply | 2 (stream) | 127 lines; reply cut off mid-docstring; not valid python | done | 38 s | D1 |
| (e) long reply | 3 (stream) | 124 lines; reply cut off mid-docstring; not valid python | done | 44 s | D1 |
| (f) `/ask` question | 1 | answered correctly in markdown; no file written | answered | 18 s | D6 |
| (f) `/ask` question | 2 | answered correctly in markdown; no file written | answered | 12 s | D6 |
| J2 resume of (a) run 1 | 1 | step 1 run again; refused again | failed (refusal) | 25 s | D7 |

Notes on the rows:

- (d): run through the repository's real-terminal driver (`tests/ux/terminal_driver.py`, ConPTY), with the key in the process environment only. Run 1 used the default mode with no flag: no prompt appeared and all three files were written (`captures/d_default_mode_pty.txt`). Run 2 added `--auto`, the only flag that attaches the approval prompt (`src/ract/ract_runner.py`, the callback choice): step 1 was approved and changed `src/calc.py`; step 2 was refused, and the run stopped with "Approval denied" (`captures/d_terminal_auto_pty.txt`). Step 3 was never asked. The resume after a refusal was not run in this terminal. The earlier piped-input runs were not a valid test of the prompt and are not counted.
- (b): the step count is not in the captures (the `Step n:` lines are absent). The three files show that three steps ran.
- (b) test file: the test in run 1 defines its own `NOTE` and does not import it, so it passes whatever `notes.py` says. The model wrote a weak test.
- J1 (setup with the preset): not run. There is no preset to run it with.

## Defects

Severity follows the repository's scale. Owners follow the senior-only list: a defect in a senior area is handed off with file and line, not fixed here.

| # | Severity | Defect | Evidence | Proposed owner |
|---|---|---|---|---|
| D1 | S1 | A reply cut off by the output limit is written as a complete file and reported done. The harness says done for a file that does not parse and, in one run, is 127 lines against a 150-line requirement. | `captures/e_long_reply_run2.txt`, `captures/e_long_reply_run3.txt`; the files end mid-docstring | BUILDER: the executor's handling of the finish reason (the stream does not report truncation to the step) |
| D2 | S1 | A new file is written without a syntax check, so invalid python is accepted and the run reports done. The write gate checks only a replacement of an existing file. | `captures/b_three_steps_run1..3.txt`: `notes.py` does not parse; pytest reports one collection error in each run | BUILDER: the write path (`executor/steps.py`, the write gate). Senior: the harness gates |
| D3 | S2 | The model copies the context label (`--- path ---`) into its reply, and RACT writes the label into the file or refuses the step because of it. | Seen in refusals (a, e) and in the written files (b, e) | BUILDER for the label strip in the step path; the Manager prompt text is senior and would need its own card |
| D4 | S2 | Default mode (no flag) in a real terminal wrote three files with no approval prompt. The approval prompt is attached only with `--auto`. The approval callback's docstring describes default mode as asking before changes. | `captures/d_default_mode_pty.txt`; `src/ract/ract_runner.py` (callback chosen per mode) | BUILDER: the approval gate. Senior: session modes (B-034); flagged, not changed |
| D5 | S3 | The probe's advice applies a local memory estimate to a hosted endpoint. | `captures/probe_doctor.txt` | WRIGHT (`doctor_advice.py`) |
| D6 | S3 | `/ask` answers in markdown with a code block, not in plain words. Already on the adjudication page as row 7. | `captures/f_ask.txt` | BUILDER, card B-010a and B-011a |
| D7 | S3 | A resumed step that was refused is reported as "interrupted". | `captures/j2_resume_a_run1.txt` (the note line and the refusal) | BUILDER |
| D8 | S3 | A tool-calling timeout is reported as "failed". | `captures/probe_doctor.txt` | WRIGHT (`capability_probe.py`) |
| D9 | S3 | The approval-denied message names the wrong step: it says "step 1" with the action of plan step 2. | `captures/d_terminal_auto_pty.txt`, the "Approval denied for step 1" line | BUILDER (the step numbering fixed in B-073; this is the approval path) |

## Gate

The release-surface set (`test_public_provenance`, `test_use_cases_catalog`, `test_source_digest`, `test_release_surface`, `test_readme_verb_index_matches_parser`) and `tests/architecture` ran in a detached scratch worktree at the report's commit: 145 passed, 1 skipped. The first run failed one check, the closed-terms check, on the model's name in the evidence. The name was then withheld from the tracked files (see Scope). No Python file changed, so the lint step had nothing to format.

## Rate limits

No 429 response and no `Retry-After` was seen in these runs. The log of attempts is empty. The sprint ran one request at a time, and no run waited on the provider.

## Fake server

Nothing in this report was seen only on the fake model server. The fake server runs in the test suite are not counted here; every row above is a run against the hosted endpoint.

## Totals

- Endpoint totals from RACT's own egress ledger, after all runs above: 41 requests, 12,394 tokens in, 5,031 tokens out, 21 requests that did not report tokens.
- Counted tokens: 17,425. The 21 requests without a token count are not included. The sprint budget is 500,000 tokens; this is far under it.

## Verdict on S2

S2 asks that a failing test be made to pass by a 7B-class and a frontier model, with the harness, not the model, deciding done.

What this report shows, for one hosted model:

- A clean single-file change and a clean failing-test fix each completed and passed their tests when the model's reply was clean (a run 3, c run 1).
- The harness reported done for three runs whose files do not parse (b), and for two runs whose files were cut off (e). So the harness's verdict is not yet a reliable signal of done.
- Refusals (the label echo, the duplication guard) wrote nothing, which is correct.

What this report does not show:

- The 7B-class leg. Not run: no local endpoint has been named, and nothing is installed. The model servers were left alone.
- A resume after an approval refusal in a real terminal. Not run.
- J1 with a preset. Not run.
- Timing to first feedback. Not measured.

The approval refusal path works in a real terminal under `--auto`, and the default mode does not ask at all (D4).

So S2 is not met. The hosted model reaches a passing change on clean replies, and the harness still says done for broken files. D1 and D2 must be fixed before a real-model S2 can pass.

## Record at landing

- This commit is the final one on the branch. It replaces the endpoint address with a placeholder in every evidence file (16 files) and records the state at landing. Earlier commits stay as they were.
- Code under test: `work/mason/integrated` at `e2cb4b6`, not landed then. The runs predate the feature tip `e00e991`. They are the evidence of record for what was run; no judgment of model behavior is made beyond these runs.
- Checks at this commit: closed-terms release check, no endpoint address, key or hosted model name in tracked files, no em-dashes, author and committer exactly `Dr. Lucas Root, Ph.D.`.

