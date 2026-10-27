# Windows file edge cases (package T)

Run date: 2026-10-26. Harness: the scratch script that drives `ract -p ... --accept-edits`
against the fake model server in a fresh git repository, once per case. The raw record for
each case is in [windows_files/results.json](windows_files/results.json) (exit code, the
output tail, and the state of the target file afterwards). The run used this worktree's own
`ract.exe` (commit 1763abc and the work() guard), so the messages below are the ones the
committed code prints.

Verdict key: **OK** = the message and the file state agree and the hint helps.
**FIXED** = a lane wording fix with a failing test first (see commit history for
`tests/test_windows_file_hints.py`). **HANDOFF** = a senior file; the file and line a fix
would go are given.

| Case | Exit | What RACT printed (summary) | What happened to the file | Verdict |
|---|---|---|---|---|
| Long path (over 260 characters) | 0 | `[step 1] done ...` and `changed: nothing` | Nothing was written. The step reports done. | HANDOFF: a silent success (see H1) |
| Reserved name `CON` | 1 | `the path component 'CON' is a Windows device name`; hint names a different file | Nothing written | OK |
| Reserved name `NUL` | 1 | as `CON` | Nothing written (the device still exists) | OK |
| Reserved name `aux.txt` | 1 | `the path component 'aux.txt' is a Windows device name` | Nothing written | OK |
| Trailing dot `notes.` | 1 | `ends in a dot or space, which Windows drops`; hint removes the trailing dot | Nothing written | OK |
| Trailing space `notes ` | 0 | `changed: notes (new, 1 line)` | Written as `notes`, not `notes ` | HANDOFF: silent rename (see H2) |
| Existing file with CRLF endings | 0 | `changed: src/crlf.py (+1 -2)` | CRLF kept | OK |
| File with a byte order mark | 0 | `changed: src/bom.py (+1 -2)` | BOM dropped; the step's content replaced the file | HANDOFF: decide whether to keep it (see H3) |
| Read-only file (`attrib +R`) | 1 | `[step 1] done src/calc.py`, then `left these paths as they are: src/calc.py (could not change it: Permission denied)`; `no files were changed` | Unchanged | HANDOFF: "done" printed before the error (see H4) |
| File locked by another process | 1 | hint `close it and run the intent again`; **also a Python traceback on stderr** (headless `-p` path) | Unchanged | FIXED for the REPL and the hint; HANDOFF for the headless traceback (H7) |
| Name differing only in case (`README.md`) | 0 | `changed: Readme.md (+1 -1)` | The file on disk stays `README.md`; the report names `Readme.md` | HANDOFF: the report names the planned case (see H5) |
| Junction into another folder | 3 | `path refused: 'linkdir' is a symlink or junction`; hint names the step | Nothing written | OK |
| Symlink file | 0 | `changed: linkfile.txt (new, 1 line)` | Written as a regular file next to the link target | OK (the file is new, not through the link) |

## Hint wording fixed in this package

| Message | Before | After |
|---|---|---|
| `could not snapshot the working tree ... Permission denied` | run `ract doctor --check-providers` | a file in the project could not be read, perhaps because another program has it open: close it and run the intent again |
| `left these paths as they are ... could not change it` | run `ract doctor --check-providers` | the file is read-only or open in another program: make it writable (`attrib -R <file>`) or close the program using it, then run the intent again |

The two tests are in `tests/test_windows_file_hints.py`. The provider check is kept for
provider errors only; a file problem never gets it.

## Traceback on a locked file (partly fixed)

The locked-file error raised `WorktreeError` (`src/ract/executor/worktree.py:740`, inside
`take_snapshot`, called from `src/ract/executor/substrate_adapter.py:253`).

- **REPL path (fixed):** `src/ract/repl.py` `_event_turn` now catches it in `work()`, prints
  `the turn stopped: <message>` once, and sets the exit code to 1. The test
  `test_a_turn_that_raises_prints_one_sentence_not_a_traceback` fails without the guard
  (the thread hook receives the RuntimeError) and passes with it.
- **Headless `ract -p` path (not fixed; H7):** the rerun of this case still prints a
  traceback on stderr. `src/ract/harness_report_enricher.py:56` catches the exception
  correctly and returns the error, but calls `logger.exception(...)`, which writes the
  full traceback. An earlier version of this page and the commit message said the
  traceback was gone; that was wrong for this path.

## Handoffs (senior; not changed in this lane)

- **H1. Long path reports done and writes nothing.** `src/ract/executor/steps.py:1136`
  sets `"outcome": "done"` for the step; no path-length check exists in
  `src/ract/workspace_path.py` `_string_checks` (line 130 onward). Fix: refuse paths over
  260 characters in `_string_checks` (or name the long-path setting) and return a refusal,
  so the outcome is `refused` and the exit code is 3.
- **H2. Trailing space is removed silently.** `src/ract/workspace_path.py:130`
  (`raw.strip()` in `_string_checks`) removes the trailing space before the segment check
  at `workspace_path.py:175` (`seg != seg.rstrip(" .")`) can see it. The check never fires
  and the file is written as `notes`. Fix: check `raw` before stripping, and refuse.
- **H3. BOM is not kept on a full rewrite.** The step's content replaces the file
  (`src/ract/executor/steps.py:377`, `:395`, `:898`, `:919` read files as `utf-8`). A
  rewrite that carries no BOM drops it. Decision needed: preserve the BOM on rewrite, or
  document that a full rewrite sets the encoding. Not a defect if the decision is the latter.
- **H4. "done" printed before a refusal to change the file.** The step's `done` line is
  printed (`steps.py:1136`) before the substrate reports the skipped path
  (`src/ract/executor/substrate_adapter.py:455`). Fix: report the step after the apply
  result is known, so a skipped path prints as skipped.
- **H5. Case-variant report names the planned case.** The changed-files line is built from
  the plan's name, not the path on disk. The source of the name is in `steps.py` near
  line 1136 (`expected_artifact`). Fix: report the name the file system returns
  (`os.scandir` or `Path.resolve` case on Windows) when it differs.
- **H6. Snapshot failure is raised from `take_snapshot`.** `src/ract/executor/worktree.py:740`
  raises `WorktreeError` for an unreadable file, and `substrate_adapter.py:253` calls it
  without a guard. The lane now handles the message, but the step should fail as `failed`
  with a clean error from the substrate rather than relying on the turn guard.

- **H7. Headless path logs a full traceback for a locked file.**
  `src/ract/harness_report_enricher.py:56` uses `logger.exception("Harness execution
  failed: %s", exc)`. Fix: `logger.error(...)` without exc_info, or log the traceback
  only at debug level. The function already returns `Rooted(error=str(exc))`, so the
  user-facing message is unchanged. Harness area, senior.

## Cases not run

- A DOS-device path with an extension (`CON.txt`) and a name ending in a space inside a
  folder were not run; the reserved-name table covers the same check.
- A file held open by a process with share mode 0 was approximated by the
  `CreateFileW` lock helper in the harness, which holds the file and does not wait.

## Sprint 6 status of each handoff (verdict and the branch that carries it)

The table above is the sprint 5 record. These are the sprint 6 fixes, each on its own branch
(see docs/review/INDEX.md for the landing order):

| Handoff | Verdict | Commit and branch |
|---|---|---|
| H1 (long path reports done) | FIXED: refused with the Windows limit sentence; step fails; no file | 2dd4d9a on work/mason/H1-H4 |
| H2 (trailing space dropped) | FIXED: the planner name keeps the space; the path check refuses it | 90e240c on work/mason/S6-5 |
| H3 (BOM on rewrite) | ESCALATE: default keeps the BOM; not implemented | none |
| H4 ("done" before refusal) | FIXED: a held step is reported only after the apply result | cd6e52e, 6233683 on work/mason/H1-H4 |
| H5 (case-variant report) | CORRECTED: the changed line already named the disk spelling; the changed list now uses the disk spelling | 3996dad on work/mason/S6-5 |
| H6 (snapshot raise) | FIXED: a repository check or snapshot failure is a failed result | ca4b530 on work/mason/S6-5 |
| H7 (headless traceback) | FIXED: one line on stderr; the traceback is at debug level | 43028e8 on work/mason/S6-5 |
| Ctrl-C at approval recorded as failed | FIXED: an interrupted step is skipped | 17354fb on work/mason/S6-5 |
| session.started "?" placeholders | FIXED: null, and the renderer's workaround removed | cdc8784 on work/mason/S6-5 |
