# UX baseline: defects

Build: after the tool-call extraction ladder landed (the session behavior is
the same as at the end of Phase 0; the later commits add test fixtures and
an unused parser). Captured on Windows 11 in a ConPTY
pseudo-terminal at 80 columns against the scripted fake model server, with
`python -m tests.ux.run_baseline`. A full test suite was running on the same
machine during capture, so absolute times are pessimistic; the relative
findings do not depend on it. No run against a real model yet: the operator
has not supplied `RACT_DEMO_BASE_URL` and `RACT_DEMO_MODEL`.

Severity: S1 blocks the journey, loses data or loses trust. S2 is confusing
or slow. S3 is polish. "Not testable today (gated)" marks a journey step
that needs the tool layer, which waits for operator ratification; it is
recorded so the later walkthrough can close it, and it is not counted as a
failure of the current build. "Card" is the board card expected to fix it; "new"
means no card covers it yet.

Each journey is compared with the golden transcript of the same name. Where
today's flow has no counterpart (no tools exist yet), the defect says so.

## Defects

| Id | Journey | Sev | What happens | Evidence | Card | Status |
|---|---|---|---|---|---|---|
| UX-01 | J4 | S1 | A "fix the failing test" turn commits the step onto the user's current branch. HEAD moves to a `rootact step 1` commit that also contains `.ract/gravity_index.json`. The working file is left unfixed, and the index holds a staged change that reverts the commit. `git diff` shows nothing, so the user sees no change and has an extra commit. | `J4.txt` harness notes; reproduced separately with `git log --all` and `git status` | new (ADR-0047 D6 replaces this path) | fixed (S-011) |
| UX-02 | J6 | S1 | Ctrl-C during a turn takes effect only when the model call returns: the main thread is blocked in the HTTP read. With an 8 s model delay the prompt came back 5.9 s after Ctrl-C, with "interrupted. Nothing further was run for that line." Correction: the first capture reported 17.8 s and no acknowledgement; that was the walkthrough driver, which did not deliver Ctrl-C at all (fixed, see `tests/ux/terminal_driver.py`). J6 was re-measured with the fixed driver after the UX-21 fix, same session code. | `J6.timeline.txt`, `metrics.json` J6 | B-033 | fixed (B-012) |
| UX-03 | J9 | S1 | After a failed turn, the next intent fails with "Session ... already exists. Use --resume to continue it or --force to overwrite." The session is stuck until the user runs `/session new`, which nothing suggests. | `J9.txt` | new (defect in `repl.py` session carry-over) | fixed (S-013) |
| UX-04 | J10, J1b | S1 | Provider down: 16 to 25 s of silence while three retries run, then a raw `[WinError 10061]` message. No hint, no named URL, no statement of workspace state. | `J10.txt`, `J1b.txt`, `metrics.json` | B-012 (`error.surfaced`), B-015 | fixed (B-043) |
| UX-05 | J1b | S1 | Following the printed first-run hint (`ract --init-provider local`) writes a config for a server that is not running. `ract doctor` then reports 7/7 checks passed. The first intent fails as in UX-04. | `J1b.txt` | B-015 | fixed (S-012) |
| UX-06 | J3 | S1 | A read-only question writes a file (`output.txt`) and commits it to the user's branch (same path as UX-01). | `J3.txt` harness notes | new (ADR-0047 D6: read-only work writes nothing) | fixed (S-011) |
| UX-07 | J3, J4 | S1 | The model cannot read files. The J3 answer comes from the plan text alone; nothing it says is checked against the code. | `J3.txt`; requests recorded by the fake server carry no file content | B-010, B-011 (gated) | fixed (read tools and checked citations shipped; re-verified on the release tip, CLI_EXPECTATIONS row 4 and the live user test) |
| UX-08 | J4 | S1 | No diff, no test run, no undo hint. The run claims `produced artifact: src/calc.py` while the file on disk is unchanged. | `J4.txt` | B-011, B-013, B-014, B-023 | fixed (change screens with line counts, /diff, /undo and granted test runs shipped; re-verified on the release tip, CLI_EXPECTATIONS rows 3, 5, 6 and the live user test) |
| UX-09 | J8 | S1 | No headless mode: `ract -p` is an argparse error (exit 2). Piped stdin is ignored (exit 2, "intent is required"). `--json` prints the human output, not JSON. | `J8.txt` | B-035 | fixed (B-035) |
| UX-10 | J3, J4, J10 | S2 | Silence while waiting: 5 s in J3, 16 s in J10, 25 s in J1b, with no heartbeat. The golden standard is a sign of life every 2 s. | `metrics.json` `longest_silence_s` | B-012 | open |
| UX-11 | J4 | S2 | Step output loses line breaks between blocks: `return a + bdef sub(a, b):`. The run report runs lines together: `Confidence: 0.0Outcomes:`. Later found (B-045): both were the capture, not RACT. ConPTY sends blank lines as a cursor jump and the driver deleted the jump; the driver now turns it into the line breaks. | `J4.txt` | B-045 | open |
| UX-12 | J4 | S2 | `/report --last` says "No loop report found", then "Assumption: no plan, Confidence: 0.0" for a run that had a plan with confidence 0.85. | `J4.txt` | B-038 | open |
| UX-13 | J2 | S2 | The prompt is a bare `ract> `. No model, branch, mode, context or tier is shown anywhere. `/settings` shows session settings but not the model. | `J2.txt` | B-012 (status line) | open |
| UX-14 | J7 | S2 | `/resume` and `/sessions` are unknown commands. There is no way to list or pick earlier sessions from the session. | `J7.txt` | B-032 | open |
| UX-15 | J1 | S2 | Bare `ract` without a terminal prints a 10-line argparse usage block and exits 2. With a terminal it opens a session with a warning, which is better, but there is no setup flow. | `J1.txt` | B-015 | open |
| UX-16 | J1 | S2 | `ract "..."` without config fails with "Configuration file not found: ract.yaml" and no next step. | `J1.txt` | B-015 (cold-boot hint) | open |
| UX-17 | J9 | S2 | The truncation explanation is correct and actionable but arrives as one 380-character line inside the error, with no separate `hint:` line. | `J9.txt` | B-012 | open |
| UX-18 | J3, J4, J6 | S3 | `quality score: 0.425` is printed after every answer with no meaning given and no way to act on it. | `J3.txt` | B-038 | open |
| UX-19 | all | S3 | The terminal title is set to the full path of the `ract` executable. | `*.raw.txt` line 2 | B-012 | open |
| UX-20 | J6 | S3 | A line typed during a running turn (`/settings`) is run after the turn ends, but nothing shows that it was queued. | `J6.txt` | B-033 | open |

## Hypotheses from UX_BAR

| Id | Verdict | Evidence |
|---|---|---|
| H1 bare prompt | Confirmed | `J2.txt` |
| H2 nothing visible until the turn ends | Confirmed: streaming defaults off; J3 shows 5 s of silence then the whole answer | `J3.timeline.txt` |
| H3 one completion per step, no file access | Confirmed | UX-07 |
| H4 no undo, checkpoint, diff or rewind | Confirmed | `J7.txt`, `J4.txt` |
| H5 bare `ract` without config | Confirmed without a terminal (usage error, exit 2). Partly retracted with a terminal: a session opens with a warning naming `--init-provider local`. No setup flow either way | `J1.txt` |
| H6 "Configuration file not found" gives no next step | Confirmed for the one-shot command | `J1.txt` |
| H7 Ctrl-C during a turn | Confirmed: it takes effect only after the model call returns (5.9 s in J6) | UX-02 |
| H8 discoverability | Confirmed: `/help` lists 15 rows; unknown commands say "Type /help" without suggesting the nearest one | `J1.txt`, `J7.txt` |
| H9 reasoning output presentation | Partly retracted: truncation is explained with the cause and the setting to change, and hidden reasoning was neither shown nor sent back (J9 harness notes). Presentation is the problem (UX-17) | `J9.txt` |

## Compared with the golden transcripts

- **J1**: golden asks at most four questions and ends at a working prompt
  with a health check that actually reaches a model. Today: no questions, a
  warning, and a hint that leads to UX-05.
- **J3**: golden shows tool cards within 300 ms and an answer citing file and
  line. Today: echo within 50 ms, then 5 s of silence, then an uncited
  answer and a file written to the user's branch.
- **J4**: golden shows the test run, a diff, review, a re-run and an undo
  hint. Today: no test run, no diff, a commit the user did not ask for and a
  claim that does not match the disk.
- **J6**: golden returns to the prompt within 2 s of Ctrl-C. Today: 5.9 s,
  after the model call returns.
- **J10**: golden names the URL, gives a hint and states that no files
  changed. Today: 16 s of silence and a raw Windows error.

## How to reproduce

```bash
python -m tests.ux.run_baseline --out docs/ux/baseline
```

Run from the repository root with the project's virtual environment. The
fake model server and the four `baseline_*_today` scenarios script the model;
nothing leaves the machine.
