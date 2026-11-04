# B-054 walkthrough: journeys J1 to J10

Run: real ConPTY terminal against the fake model server (`tests/fixtures/fake_model_server.py`),
80 columns by 40 rows, Windows 11, Python 3.11.15. Transcripts sit beside this file
(`J1.txt` ... `J10.txt`), timings in `timings.txt`. Every quote below is copied from a capture.

Severity: S1 blocks the journey, S2 wrong or misleading output, S3 cosmetic or wording.
Owner is the card that would fix it, or "unassigned" when no card covers it yet.

## Not runnable today (not defects)

- **J3** (read-tool loop): no scenario in the fake server drives a read-only tool loop; not run.
- **J5** (per-hunk accept or reject): not built; B-014c.
- **J7** (Esc Esc rewind): not built; only `/resume` exists.
- **J8, stdin piping**: the headless run was run with `-p` and argv only; piped stdin was not tried.

## Findings

| ID | Journey | Sev | Finding (captured text) | Owner |
|---|---|---|---|---|
| D1 | J6 | S2 | After Ctrl-C the final checklist still shows steps 2 and 3 as `[ ]` (pending): `[ ] 2. Add src/notes.py with the NOTE constant`. They never ran and were not marked skipped (`[-]`). | B-053b (the lane) |
| D2 | J6 | S1 (known) | Ctrl-C during a turn works (`Stopped. The model call is still finishing in the background; nothing it returns will be written.`), but no queue or working indicator is shown while the call finishes. | B-033 (waits) |
| D3 | J9 | S2 | A weak-model reply with no steps prints `error: Planning failed: Plan contains no steps.` followed by `hint: run ract doctor --check-providers to check the setup`. The provider answered, so the hint points at the wrong cause. | unassigned |
| D4 | J9 | S2 | With no pending question on screen, the runner typed `y` at the REPL, and RACT sent it as a new intent: `ract> y` then `error: Planning failed: Plan contains no steps.` A second model request was made (`1 model request, 0.5 s`). | unassigned |
| D5 | J8 | S3 | Turn summary reads `src/notes.py (new, 1 lines)`. The plural is wrong. Known from the earlier FOUND list; the fix is in `describe_change` (turn_summary.py). | unassigned |
| D6 | J4 | S2 | The user asked to fix `tests/test_calc.py::test_add fails`. The turn ran no tests, and the verified line says so: `verified: RACT ran no tests this turn`. The result is honest, but nothing offers to run the failing test. | unassigned |
| D7 | J4, J8, J6 | S3 | Provenance warning on every write: `warning: provenance: 1 file(s) written without a Rootknot (src/calc.py). Signing is not wired into this release`. Accurate, but it repeats on every turn with no way to dismiss it. | unassigned |
| D8 | J10 | S3 | Under scripted faults the retries show, then `error: Planning failed: Provider call failed: HTTP 503: {"error":{"message":"fake server error 503"...` prints the raw provider body. Usable, but noisy. | unassigned |
| D9 | J10 | S3 | `4 model requests, 6.4 s, tokens not reported`. Tokens are missing for failed calls, which is expected, but the line does not say why. | unassigned |

## Carried from earlier FOUNDs (not re-captured in this batch)

- Heartbeat line `waiting on model` lands on the approval prompt at 60 columns (B-033, input area).
- `/ask` prints a plan first and the raw reply JSON (see `docs/SESSION_GUIDE.md`, known issues).
- `/resume` summary can wrap mid-word at 80 columns; not seen in this batch, not retested.
- No `/diff` command exists.

## Timing

From `timings.txt`, time to first feedback: J1 7.11 s (includes the default-port probe),
J2 2.86 s, J4 2.12 s, J6 2.13 s, J9 1.53 s, J10 2.31 s. The longest silent stretch is in J4:
the approval wait prints `... waiting on model` every 10 s, so nothing goes quiet longer than 10 s.

## J1 re-run (answered `n` at the setup prompt)

The first J1 run typed `/exit` at the setup question, which is a runner error; that capture
is superseded. The re-run answered `n` and is in `J1.txt`. It shows:

- `Set one up now? [Y/n] (n opens the session without one) n`, then the session opens.
- `⚠  ract.yaml not found. Leave and run ract setup to create one (it checks this machine and asks a few questions).`
  The word "Leave" is unclear: the session does not exit. S3.
- `RACT session ? via ? | default | T3 off`. The model shows as `?` with no config. Correct
  but unexplained. S3, owner unassigned.
- No `ract.yaml` was written (`ract.yaml written: False`), which matches answering `n`.

Added to the findings table (see D10 and D11 below).

| ID | Journey | Sev | Finding (captured text) | Owner |
|---|---|---|---|---|
| D10 | J1 | S3 | `Leave and run ract setup to create one`: the session does not leave, so "Leave" misleads. | unassigned |
| D11 | J1 | S3 | Status line `RACT session ? via ? | default` with no config. The `?` values are not explained. | unassigned |

## Walkthrough notes

- The J1 setup question was answered `n` in the re-run. Before the re-run, the setup question
  had been answered with the runner's `/exit`, which is why the first capture showed
  `ract.yaml written: no` for the wrong reason.
