# Scale (package Q, ux-more)

Medians and worst cases over five runs each, on this machine, 2026-10-26. Raw numbers in
`docs/ux/scale_raw.txt` (checklist, diff, reply, sessions) and in the sprint log (the REPL).

| Case | Median | Worst | Growth check |
|---|---|---|---|
| Checklist, 100 steps (plan, start and finish per step, final block) | 0.012 s | 0.013 s | |
| Checklist, 500 steps | 0.056 s | 0.058 s | |
| Checklist, 1000 steps | 0.112 s | 0.117 s | linear: 2x steps, 2x time |
| Turn diff, 1000 changed lines (exact hunks) | 0.085 s | 0.086 s | |
| Turn diff, 5000 changed lines (summarized after the fix) | 0.003 s | 0.004 s | before the fix: 2.547 s median, 2.662 s worst |
| Turn diff, 5001 lines (past the cap) | 0.003 s | 0.003 s | |
| Model reply, 100 KB on one line | 0.072 s | 0.077 s | |
| Model reply, 200 KB on one line | 0.155 s | 0.179 s | linear: 2x size, 2x time |
| `/sessions` with 2000 saved sessions | 0.255 s | 0.276 s | the listing reads only the newest ten |
| REPL, 200 turns in one session (event mode, fake server) | 110 ms per turn | 486 ms | first 20 turns median 87 ms; last 20 median 120 ms; total 22.4 s |

## What changed

- **The turn diff.** The exact matcher grew quadratically between 1000 and 5000 lines (0.085 s
  at 1000, 2.547 s at 5000). The exact range now ends at 2000 lines; past it the turn shows the
  line counts. The test `test_a_five_thousand_line_diff_is_summarized_within_a_time_bound` bounds
  the time (`src/ract/diff_render.py`, `_MAX_DIFF_LINES`). Three tests that pinned exact hunks at
  2500 to 3000 lines moved to sizes inside the exact range (`tests/test_diff_render.py`).

## Not fixed, measured

- **The REPL turn cost grows with the session (hypothesis, not isolated).** 200 turns: the median
  rose from 87 ms to 120 ms, about 0.17 ms per turn. The likely cause is the session file rewritten
  in full each turn (the run layer, BUILDER). Not measured further here. Handoff: measure the session
  file size against turn count and write it incrementally, or keep only the last turns in memory.
- **The checklist and the reply path are linear.** Nothing to hand off.
- **Sessions list.** Each row is one file read and one stat; 2000 files cost 0.26 s. A cap on
  the directory scan would help beyond about 10000 files. Handoff to the run layer, not urgent.
