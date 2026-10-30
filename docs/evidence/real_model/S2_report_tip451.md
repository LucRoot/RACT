# S2 real-model re-run on the feature tip 451f11c (decision D-120, D-121)

Status: partly run. One hosted provider (the structurer role). The local 7B-class leg is not run (decision E). S2 stays not met.

## Scope

- Code under test: the feature branch at 451f11c, exported in a detached worktree. Nothing in src/ was changed for these runs.
- Provider: the hosted provider, through the OpenAI-compatible adapter, with a scratch ract.yaml (no preset, D-086). The endpoint address, the model name and the key are not in this file or in the captures. The key was provided to the RACT process from the provider's environment file for each run, and never printed, logged or written.
- One process at a time. No test suite was run during the runs. The runs happened while a BUILDER gate held QUIET.md, under D-121.
- Dates: 2026-10-30, between 10:24 and 10:40 PT.

## Rows

Verdict is the harness's (what RACT printed and its exit code). "Wall" is the run's wall time.

| Row | Run | Result | Harness verdict | Wall | Notes |
|---|---|---|---|---|---|
| (a) one-file change | run | src/calc.py fixed (return a + b) | done | 12 s | "verified: RACT ran no tests this turn" |
| (b) three-step change | run | three files written; tests/test_notes.py does not import src.notes | done | 29 s | FOUND 2, see below |
| (c) failing test made to pass | run | src/calc.py fixed | done | 9 s | FOUND 3, the test was never run |
| (d) default mode, no flag, pseudo-terminal | partly run | "Run it? [a]pprove [s]kip <n> [e]dit <n> [c]ancel" shown before any write; the answer was not sent | (waiting for approval) | ~60 s | B-101 holds on the hosted run; approve, skip, edit and cancel not run |
| (d) --auto, pseudo-terminal, plan approved once | run | the plan was shown and approved with a; src/calc.py fixed; step 2 was prose ("tell the user to run pytest") and no test was run | done | ~60 s | the approval is per plan, not per step (D4 still holds); no test run, so the harness shows no verification |
| test file imports a name that does not exist | run | tests/test_missing.py written; the import is not refused | done | 16 s | FOUND 1 |
| no terminal, no --yolo | run | refused, exit 3, names --yolo; no file changed | refused | 12 s | B-104 holds on the hosted run |
| (e) long reply | not run | | | | |
| (f) /ask question | not run | | | | |

## Defects found

| # | Defect | Evidence | Owner |
|---|---|---|---|
| 1 | A step that writes a test file whose import names a symbol the target module does not define is reported done. tests/test_missing.py:1 is `from src.notes import NOTEX`; src/notes.py does not exist in this project, so the import cannot resolve. B-102 is meant to refuse it (a static import check on the files a step writes). | captures/nofile.txt (the "changed: tests/test_missing.py (new, 5 lines)" line) | BUILDER (B-102 did not catch this case) |
| 2 | A step that writes a test which does not import the module under test is reported done. tests/test_notes.py:1 defines `NOTE = "two"` itself instead of importing it from src.notes, so the test checks a copy. The three steps are shown as passed. | captures/b.txt (the "[x] 3. Create tests/test_notes.py" line); runs/b/tests/test_notes.py:1 | BUILDER (the verdict for a step with added tests) |
| 3 | A failing-test task ends done without the test run. The model fixed src/calc.py:2 and the harness said "done", with "verified: RACT ran no tests this turn". The task was to make a failing test pass, and no test was run. | captures/c.txt (the "verified" line) | BUILDER (verification for a test-fix task) |

Defect 1 and 2 are the same class as D10 on the earlier tip: a file that is wrong, reported done. The MANAGER is told in the same entry in the team log.

## Totals

Endpoint totals are in RACT's egress ledger for the runs. Not reproduced here.

## Verdict

On tip 451f11c, against the hosted provider:
- B-104 holds: no terminal and no --yolo exits 3 and changes no file.
- B-101 holds for default mode: the approval prompt appears before any write.
- B-102 does not hold: a test file that imports an undefined name is written and reported done.
- The harness reports done for test-fix and test-writing steps without running tests (defects 2 and 3).

S2 stays not met: the local 7B-class leg is not run, and the (e) and (f) rows are not run.
