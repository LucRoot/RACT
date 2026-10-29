# S2 real-model re-run on the feature tip (B-098)

Status: partial. One hosted provider was used for the runs below. The local 7B-class leg is not run: no local endpoint has been named (decision E). S2 stays not met.

## Scope

- Code under test: the feature tip `d5dbda0` (the BUILDER's LANDED entry, 13:38 PT on 2026-10-29), exported read-only from git. The landed tip includes the S2 fixes for D1, D2, D3, D7 and D9 (B-095, B-096, B-097) and the probe changes (B-094).
- Provider: the hosted provider, a large hosted model (its structurer role), through the OpenAI-compatible adapter. The repository has no preset for it. The scratch `ract.yaml` names the endpoint and reads the key from the environment. The endpoint address, the key and the model name are held on the operator board, not in this file.
- Date: 2026-10-29, between 13:50 and 14:35 PT. One request at a time.
- Key: loaded into the environment of each RACT process for that run only. Captures were scanned before commit: no key prefix, no endpoint address, no model name.
- Captures: `docs/evidence/real_model/tip/`. Each file's header names the commit, the date and the settings.

## Task by run

Verdict is the harness's (what RACT printed and its exit code). "Wall" is the run's wall time. "First feedback" was not measured.

| Task | Run | Result | Harness verdict | Wall | Notes |
|---|---|---|---|---|---|
| (a) one-file change | 1 (stream) | `src/calc.py` fixed; 2 tests pass | done | 22 s | matches the earlier pass |
| (b) three-step change | 1 (stream) | three files written; `notes.py` correct; `tests/test_notes.py` imports `NOTE` from `src`, not `src.notes`, so the test module fails to import (1 error) | done | 57 s | FOUND, see D10 |
| (c) failing test made to pass | 1 (stream) | `src/calc.py` fixed; 3 tests pass | done | 19 s | matches the earlier pass |
| (d) approval | 1 (default mode, no flag, terminal driver) | no prompt at all; all three files written | done | about 100 s | D4 still holds |
| (d) approval | 2 (`--auto`, terminal driver) | one plan-level prompt ("Run it? [a]pprove [s]kip <n> [e]dit <n> [c]ancel"); approved; no per-step prompt after that; all three files written | done | about 90 s | the plan approval replaces the per-step prompt; see D4 |
| (d) approval | 3 (`--auto`, plan cancelled with `c`) | "Plan cancelled: nothing was run and no file changed." | failed (cancelled) | about 20 s | correct; the hint line is wrong, see D11 |
| (e) long reply | 1 (stream) | refused: "Step 1's reply for src/report.py was cut off twice (finish reason ...)"; no file written | failed (refusal) | 39 s | D1 is fixed: a cut-off reply is not done |
| (f) `/ask` question | 1 | answered in markdown; `add()` described as `a - b`, which is what the file holds; no file written | answered | 6 s | answer is correct for the repository |

Notes on the rows:

- (b): the harness said done, but the test module the run wrote does not import. This is the same failure class as D2 ("done" with a file that is not right), now in a test file that parses. The run does not show that the harness ran the tests.
- (d): the earlier piped-input run and the earlier default-mode run are the same behaviour on this tip: default mode asks nothing and writes all three files. With `--auto`, the plan is approved once and the steps run without a per-step prompt. A plan can be cancelled, and then nothing runs.
- (e): one run. The earlier runs of this task (two cut off, one refused by the duplication guard) are in `S2_report.md`.
- The three test files of each run were not all run by the harness.

## Defects found on the tip

| # | Severity | Defect | Evidence | Proposed owner |
|---|---|---|---|---|
| D10 | S2 | The harness says done for a run whose written test module fails to import (`from src import NOTE`). The write gate checks that a file parses, not that the tests it adds can be collected. | `captures/b_three_steps_run1.txt`; the run's tests fail on collection | BUILDER (the verdict of a run with added tests) |
| D11 | S3 | A plan the user cancels with `c` gets the hint "run ract doctor --check-providers to check the setup", which does not apply. | `captures/d_auto_tip_*` and `captures/d_cancel_tip_*` (the cancel run) | BUILDER (the hint for a user cancel) |
| D4 | S2 (confirmed) | Default mode, no flag, in a terminal: no prompt, files written. `--auto` asks once for the plan and not for each step. The approval gate is per plan, not per change. | `captures/d_default_tip_*`, `captures/d_auto_tip_*` | BUILDER and the operator (session modes, B-034) |

D1, D2 and D3 from the earlier report are not seen on the tip: D1 is refused in (e), D2 is not reproduced for `notes.py` in (b), D3 (the label echo) did not appear in these runs.

## Rate limits

No 429 response and no `Retry-After` in these runs. Requests were sequential.

## Totals

- Endpoint totals from RACT's egress ledger after the runs: 53 requests, 16,440 tokens in, 6,583 tokens out, 28 requests that did not report tokens. The increase since the earlier report (41 requests, 12,394 in, 5,031 out) is this re-run.
- Counted tokens this sprint, with the earlier report: 23,023. The sprint budget is 500,000 tokens.

## Verdict

This re-run, on the feature tip, shows:

- The clean one-file change (a) and the failing-test fix (c) pass with the harness reporting done.
- The cut-off reply (e) is refused, so D1 is fixed on the tip.
- A cancelled plan writes nothing, which is correct.
- Default mode still writes without asking (D4).
- The harness reports done for a three-step run whose test module does not import (b). The run does not show that the harness ran the tests. D10 is open.

What this does not show:

- The 7B-class leg. Not run (decision E).
- A failing test made to pass by a frontier and a 7B-class model with the harness deciding done. Not shown: one hosted model only.

So S2 stays not met.
