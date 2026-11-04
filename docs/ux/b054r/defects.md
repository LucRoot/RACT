# B-054r: walkthrough re-run on the merged tip (integ-check, 994bb6f)

Run: real ConPTY terminal (80x40) against the fake server, Windows 11, Python 3.11.15.
Full run on 45ad0db with `walk_b054r.py` (J1, J2, J4, J6, J8, J8 with stdin, J9, J10).
J1 and J2 re-captured on 994bb6f after the D11 fix (e2a0474). Transcripts beside this
file. Quotes are copied from the captures. Severity words as in `../b054/defects.md`.

Not runnable, unchanged from the first run (not defects): J3 (no read-tool scenario),
J5 (per-hunk accept or reject, B-014c), J7 (Esc Esc rewind not built).

## Status of the first-run defects

| ID | Sev | First run | This run | Evidence |
|---|---|---|---|---|
| D1 | S2 | steps left `[ ]` after Ctrl-C | fixed | J6: `[-] 2. Add src/notes.py ... (0.0s) skipped` |
| D2 | S1 (known) | no queue indicator during Ctrl-C | remains (B-033, waits) | J6 unchanged |
| D3 | S2 | provider-check hint on an empty plan | fixed | J9: `hint: the model returned no steps for this intent; rephrase it ...` |
| D4 | S2 | a lone `y` sent to the model | fixed | J9: `ract> y` then `no question is waiting; to send that text as a request, add a word to it` |
| D5 | S3 | `(new, 1 lines)` | fixed | J8: `tests/test_notes.py (new, 5 lines)`; the one-line case is in `test_b054f_wording`, `test_turn_summary` |
| D6 | S2 | `verified: RACT ran no tests this turn`, nothing offers to run them | remains (proposed BUILDER) | J4 line 40, unchanged |
| D7 | S3 | provenance warning every turn | fixed in the renderer; not shown by a multi-turn capture | J4 (one turn) prints it once; test `test_the_provenance_warning_prints_once_per_session` |
| D8 | S3 | raw JSON body in the error | fixed | J10: `error: Planning failed: Provider call failed: HTTP 503: fake server error 503` |
| D9 | S3 | `tokens not reported` | fixed | J10: `4 model requests, 6.4 s, tokens not reported by the provider` |
| D10 | S3 | `Leave and run ract setup` | fixed | J1: `ract.yaml not found. Run ract setup in another terminal to create one` |
| D11 | S3 | `RACT session ? via ?` | fixed (renderer; the event keeps its placeholder) | J1 on 994bb6f: `RACT session no model via no provider` |

## New or still-open items seen in this run

- **Heartbeat on the approval question (out of lane, B-033s).** J4 at 80 columns:
  `src/calc.py? [y/N]:   ... waiting on model (4 s)`. The first tick is appended to the open
  input prompt. Same condition as the 60-column rich-mode capture in the 18:10 FOUND of
  the lane log. Owner: BUILDER (B-033s).
- **J8 with stdin (new).** `ract -p --accept-edits --config ract.yaml --output-format json`
  with the intent on stdin exits 0 and prints `"schema": "ract.result/1"`, `"outcome": "done"`,
  and `"changed": ["src/calc.py", "src/notes.py", "tests/test_notes.py"]`. The intent
  reached the run; no defect found on this path.
- **Event placeholder (ESCALATE, not changed).** `session.started` still carries `"?"` when no
  config names a model. The renderer now reads it as "no model". Changing the event field
  is an ESCALATE for the BUILDER.

## Timing

First feedback: J1 2.25 s, J2 1.72 s, J4 1.87 s, J6 3.71 s, J9 2.25 s, J10 2.68 s (run
timings in `timings.txt`; J1 and J2 from the 994bb6f re-capture).
