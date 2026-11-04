# Terminal matrix (package H, ux-next)

The same journey in each console installed on this machine, in a real ConPTY: start `ract`,
one three-step intent with three approvals (`y`), `/help`, `/sessions`, `/exit`. Plus Ctrl-C
during the first turn, a paste approximation, and the legacy code page checks. Captures are
in `docs/ux/terminal_matrix/` (plain `*.txt`, raw with escape codes `*.raw.txt`). Nothing was
installed. The final numbers come from the run on the tip of this package (see the log).

Consoles: **ConPTY direct** is our driver's pseudo-terminal (the Windows ConPTY API that
Windows Terminal also uses), running `ract.exe` with no shell in between. **PowerShell 5**
is `powershell.exe`. **PowerShell 7** is `pwsh.exe`. **cmd** is `cmd.exe /d /q /c`. **Git
Bash** is `bash.exe -l -c`. **Windows Terminal** is installed (`wt.exe`) but is a host
window, not a shell; the driver cannot capture its window, so its cells are `unknown`.

Legend: ✔ checked in a capture; ✖ failed in a capture; `unknown` not run here (reason given).

| Feature | ConPTY direct | PowerShell 5 | PowerShell 7 | cmd | Git Bash | Windows Terminal |
|---|---|---|---|---|---|---|
| Launch to first prompt (seconds) | 2.26 | 5.22 | 2.90 | 3.28 | 6.29 | unknown (host) |
| Journey completes: 3 approvals, `/help` table, `/sessions`, `/exit` | ✔ | ✔ | ✔ | ✔ | ✔ | unknown (host) |
| Box drawing renders (rounded corners, table rules) | ✔ | ✔ | ✔ | ✔ | ✔ | unknown (host) |
| Check marks `✓` render | not printed by the journey; ✔ in the legacy intent echo | same | same | same | same | unknown (host) |
| Colours (SGR codes present in the raw output) | ✔ | ✔ | ✔ | ✔ | ✔ | unknown (host) |
| Width: no line over 80 columns | ✔ (0 lines) | ✔ | ✔ | ✔ | ✔ | unknown (host) |
| Ctrl-C during a turn: `stopping...`, prompt returns | ✔ | ✔ | ✔ | ✔ | ✔ | unknown (host) |
| Paste (two lines in one write; approximated, not a real paste) | ✔ both lines read | ✔ | ✔ | ✔ | ✔ | unknown (host) |
| Console code page | not measured (driver default) | IBM437 | ibm437 | 437 | UTF-8 (`locale charmap`) | unknown (host) |
| Legacy code page 437, PYTHONIOENCODING unset, non-ASCII intent, file name and reply: readable, no UnicodeEncodeError | ✔ | ✔ (`[Console]::OutputEncoding` 437) | not run | ✔ | not run | unknown (host) |
| Legacy code page 1252, same text | not run | not run | not run | ✔ | not run | unknown (host) |

Captures: `docs/ux/terminal_matrix/<console>_journey.txt`, `<console>_ctrl_c.txt`,
`<console>_paste.txt`, the raw versions beside them, `codepages.txt`, `legacy_cmd_cp437.txt`,
`legacy_cmd_cp1252.txt`, `legacy_powershell5_cp437.txt`, `legacy_conpty_default.txt`, and
`legacy_results.json`.

## Redirected output (not a console)

`ract -p ... --output-format json` with stdout sent to a pipe, PYTHONIOENCODING unset, a
non-ASCII intent and a non-ASCII plan: the JSON is valid UTF-8 and there is no
`UnicodeEncodeError` (`scratchpad` probe, 2026-10-26; the turn itself failed at the
duplication guard because the fixture wrote a copy of `calc.py`, a fixture artifact).

## What the matrix found

1. **Fixed: the approval answer wrapped onto the next line at 80 columns.** The question was
   folded to the full width, so the typed answer went to a new physical line. Now the question
   folds to three columns less (`src/ract/approval_callback.py`; tests in
   `tests/test_approval_prompt_fit.py`).
2. **Fixed: Ctrl-C at the approval prompt left the next output on the question's line.** The
   prompt now prints a newline before the interrupt propagates (same file and tests).
3. **Handoff (BUILDER, executor): a Ctrl-C at the approval prompt is recorded as a failed step.**
   The matrix shows `[!] 1. ... failed` before `stopping...`. The renderer shows a stop that
   comes first as skipped; the executor's exception path is the place to fix it
   (`docs/ux/errors_check.md` row 14; `src/ract/executor/steps.py`).
4. **Partly fixed: the duplication guard's hint.** The legacy transcript showed
   `hint: run ract doctor --check-providers`, which did not match the cause
   (`docs/ux/terminal_matrix/legacy_cmd_cp437.txt`). Package R (9c27911) fixed the hint: it now
   reads "the change repeats code that already exists in the project; ask for something new, or
   name the existing code you want reused" (`src/ract/session_turn.py`, tests in
   `tests/test_duplication_hint.py`). The message's jargon (`sub (src.calc) similarity=0.974`) is
   still a handoff: `src/ract/duplication_guard.py` line 28 and `src/ract/executor/steps.py`
   lines 1481 and 1484 (BUILDER). The transcript above predates the hint fix.
5. **Not a defect: the fixture.** The legacy scenario's first step wrote a copy of `calc.py` under
   a new name, which the duplication guard refuses. The file-write check is therefore not
   evidence here; the readability check is.

## Not covered by this matrix (the cells above say `unknown` or `not run`)

- Windows Terminal itself (host window; not capturable by the driver).
- Real paste (a clipboard paste is not reproduced; the two lines arrive in one write).
- PowerShell 7 and Git Bash under the legacy code pages, and code page 1252 outside cmd.
- Narrow widths in every console (widths 40 and 60 are covered in ConPTY by `docs/ux/width_a/`).
