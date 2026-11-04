# Sprint 7 journeys (package 5)

Run: `python -m tests.ux.run_baseline --only J1,J1b,J2,J3,J4,J6,J7,J8,J9,J10` with `RACT_UX_COLS=80`
and `RACT_UX_COLS=60`, on the landed feature tip `"[S7] Rebased onto the landed feature tip (L-21): format the"` (BUILDER's landing, L-216), from a detached
worktree. Captures: `docs/ux/sprint7/journeys/80/` and `docs/ux/sprint7/journeys/60/` (the rendered
`.txt`, plus the raw and timeline files the runner writes beside them).

Result: all ten journeys finished with the runner's `exit 0` at both widths (80 columns: 43 s for J1,
30 s for J1b, 4 to 11 s for the rest; 60 columns the same). No traceback, no "the turn stopped" line.

| Journey | What it is | 80 columns: rendered lines over 80 | 60 columns: rendered lines over 60 |
|---|---|---|---|
| J1 | first run in an empty directory, no config | 10 | 16 |
| J1b | first run following the printed hint | 1 | 18 |
| J2 | daily start in a configured repo | 1 | 1 |
| J3 | ask about the code (read-only) | 2 | 2 |
| J4 | fix the failing test (no answer to the approval question) | 2 | 2 |
| J6 | interrupt during a slow turn | 1 | 1 |
| J7 | resume an earlier session | 1 | 1 |
| J8 | headless use | 6 | 9 |
| J9 | weak or reasoning model | 1 | 1 |
| J10 | provider is down | 1 | 1 |

## Look-again pass 1 (what the captures say)

- **J4** ends with "Approval denied for step 1" and no files changed. The journey script sends no answer
  to the approval question, so the question reads end of input and the step is denied. The sprint 6
  capture (`docs/ux/sprint6/60/J4.txt`) shows the same denial, so this is not a sprint 7 regression. It
  is the journey as scripted; a journey that approves would need `approve` added to its script.
- **J6** shows the `/settings` table at the end, not an interrupted turn. The interrupt itself is not in
  the rendered capture; the timeline file has it. Stated, not claimed as shown.
- **J8** prints the headless error sentences and a JSON result line. The JSON line is the headless
  contract (`ract.result/1`) and is the reason for most of J8's over-width lines.
- **J1** and **J1b** print the setup text: "Set one up now? [Y/n] ...", the server and model suggestions,
  and a `# build:` header line that carries the commit subject. The setup prompts run past the width at
  both widths. That is the setup flow's output (not the plan approval), and it is a width defect for the
  setup flow's owner. Not fixed here.

## Look-again pass 2 (the over-width lines, by kind)

- Setup text (J1, J1b): 10 and 18 at 80 and 60 columns. Handed off: the setup flow prints lines wider
  than the terminal; the owner is the setup lane (BUILDER).
- Headless JSON (J8): the `ract.result/1` line. A contract line, not a layout line. Not a defect.
- Journey header (`# build:` line): the runner writes the commit subject into the capture header. The
  header is the runner's, not RACT's output; a fix is to wrap the header in the runner.
- Everything else (1 or 2 lines each): the echoed input and the step lines the capture records, at
  the width the journey ran with. Not fixed here.

Escape sequences and the raw JSON in the `.raw.txt` and `.timeline.txt` files are excluded from the
counts above on purpose; they are the terminal's own bytes, not the rendered screen.
