# Slice (a) walkthrough: the tool layer with review and undo (B-110)

A real pseudo-terminal walk (D-003) of slice (a) against the scripted fake model
server, at 80, 60 and 40 columns, recorded by `python -m tests.ux.run_slice_a`.
The walk runs this checkout's code (`python -m ract.cli` with `PYTHONPATH` on
its `src`), with `agent.step_tools: true` in a throwaway workspace. Each width
has, per journey, `<id>.txt` (escape sequences removed), `<id>.raw.txt`,
`<id>.timeline.txt`, and `metrics.json`.

ConPTY's rebuilt plain text joins repainted lines and can drop the space after
a prompt (`answer:r`), so the `.txt` files are not the screen; the file states
in the harness notes and the metrics are the facts.

## Journeys

| Id | What it walks | Ends with |
|---|---|---|
| SA1 | A failing test, fixed with the tools: the model reads `src/calc.py`, edits it with the digest it read, and writes `notes/fix.md`. The changes are proposed; the operator rejects the note and accepts the fix, hunk by hunk, before anything is applied. Then `/diff` and `/checkpoint`. (J5 with the new flow) | `src/calc.py` fixed; `notes/fix.md` never written |
| SA2 | An edit to `AGENTS.md`, a control file: the tool card shows `[T2]`, the tier-2 question shows the change, the operator allows it for the session (`s`), then accepts the proposed hunk. | `AGENTS.md` changed |
| SA3 | J7: two turns change `src/calc.py`; `/rewind` lists them by their requests; the operator picks the first. | `src/calc.py` as the first turn left it |
| SA4 | J3: a question reads the project with the tier-0 tools. No workspace, no question. | an answer; nothing changed |

## Answers typed per task (condition 3)

Counted by the harness: lines typed in answer to a question, not commands.

| Task | 80 | 60 | 40 | The answers |
|---|---|---|---|---|
| SA1 fix a failing test (two files proposed) | 2 | 2 | 2 | one per proposed hunk; the per-step question is replaced by the review |
| SA2 change a control file | 2 | 2 | 2 | the tier-2 question, then the hunk |
| SA3 two changes, then rewind | 3 | 3 | 3 | a hunk per turn, then the turn to go back to |
| SA4 ask about the code | 0 | 0 | 0 | none |

## Times

- **"preparing a workspace for the changes"**, from the request: 0.9 to 1.1 s on
  the first turn (the planner's model request is inside that time), 0.4 to
  0.5 s on SA3's second turn. The line is printed before the base snapshot and
  the step worktree, so it comes before any tool call of the step.
- **The step worktree on a 10,000-file repository** (the card's 3 s target;
  a throwaway script built the repository and timed `take_snapshot` and
  `WorktreeManager.create`, three runs), while a full gate ran
  on the same machine: snapshot 0.78 to 0.81 s, worktree 2.95 to 3.32 s, total
  3.74 to 4.11 s. Over the target under load; the number with the machine idle
  is recorded on the board.

## Found in the walk, and fixed before this recording

1. A proposed file that is not split into hunks asked "r restore the saved
   copy", and nothing is saved before an apply: it now asks "a apply, r leave
   it out".
2. Each proposed hunk was drawn twice, by the `diff.proposed` line and by the
   question: the event now renders one line with the hunk count.
3. A control file showed `[T1]` on its tool card and on its proposed line: both
   now show the call's tier, `T2`.

## Not in this walk

- The hosted model (the evidence run follows).
- Esc Esc on Windows: the Windows console's line editor clears the line on Esc
  and RACT never sees the key, so SA3 uses `/rewind` (escalated to the MANAGER).
- The not-a-git-repository offer and an unanswered review are covered by
  real-turn tests (`tests/test_git_init_offer.py`, `tests/test_proposed_review.py`),
  not by this walk.
- the screens for the slice (the diff.proposed screen with hunk ids, the
  apply result, the `/checkpoint` and `/restore` listings, the git init offer).
