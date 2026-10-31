# J5 walkthrough: review a change hunk by hunk (B-117)

Recorded 2026-10-30 in a real pseudo-terminal (`tests/ux/run_baseline.py --only J5`, RACT_UX_COLS 80 and 60) against the fake model server (scenario `baseline_j4_today`, one file, one hunk). Build: `6dd6924` (B-105 on the feature tip `ee20d3a`, which carries `/review`).

Files: `J5_80.txt` and `J5_60.txt`. The header of `J5_60.txt` says "80x40" because the runner writes that label for every run; the terminal in that run was 60 columns (the wrapping shows it).

## What the walk shows

- A fix turn asks once (`[y/N]`), writes `src/calc.py`, and prints the summary: one file, `+1 -1`, the hunk, and `way back: /undo, or /review per hunk`.
- `/review` shows the hunk and the choices; `r` (reject the rest of the file) puts the turn's saved copy back, and `/diff` runs afterwards.
- No line of terminal output is wider than the terminal (80 and 60 runs, measured without the harness notes).

## What the walk does not show (the card asks for these)

- A three-file change. The scenario changes one file with one hunk.
- An accept, a reject and an edit of separate hunks. Only the reject of the rest of the file is driven.
- `/undo` after the review. The walk runs `/diff` there.
- So the card's full acceptance is **not met** by this walk. It stays open until a scenario with three files exists (the fake server has to script it; no scenario is changed in this card).

## Defects for the BUILDER (file and line, from the captures)

1. **The status line folds inside "T3 off" at 60 columns.** `src/ract/session_render.py:159` builds `... | T3 {tier3}`; at 60 columns the capture reads `... | T3` then `  off` (`J5_60.txt` lines 6 and 7). Keep the tier item on one line (fold before `| T3`, not inside it).
2. **The review's choice prompt folds in the middle of a phrase** at both widths: `R reject` / `the rest of the file:` at 80 (`J5_80.txt` lines 48 and 49), and `A accept the rest of` / `the file, R reject the rest of the file:` at 60 (`J5_60.txt` lines 51 and 52). The text is `src/ract/review_hunks.py:33-35` (`CHOICES`), printed through `_ask` at line 196. Fold at the commas, one choice per line, or keep each choice whole.
3. **The prompt after the review has no space:** `ract>/diff` (`J5_80.txt` line 51; `J5_60.txt` line 54), where every other prompt reads `ract> /exit`. The line after the review answer `r` also carries the answer on the same line (`file:r`). Unexplained from the capture alone: it may be the driver's echo at the end of the review loop. The BUILDER should check it in a real terminal before it changes anything.
4. **Minor:** `changed: ... review with git` / `    diff` splits the words `git diff` at 60 columns (`J5_60.txt` lines 24-25).

## The three-file walk on the landed tip 1a7d33d (D-145), 80 and 60 columns

The same scenario (`j5_three_files`) and the same keys as the walk above, run on the feature tip after the B-137 batch and D-145 landed: `landed_80.txt` and `landed_60.txt`. Every terminal line is within its width.

What changed since the first recording: the status line shows `T3 off (no grant)` on its own item, and each walk prints `removed src/.calc.py.rootknot.json (the turn created it)` at `/undo`: the signed record beside each file is removed with the file it recorded (the landed `.<name>.rootknot.json` record). The plan's first approval, the review hunks, the edit, the reject and `/undo` work as before.
