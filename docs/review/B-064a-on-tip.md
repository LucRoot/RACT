# B-064a on the feature tip (sprint 7, package 1, re-entry)

Branch `work/s7-on-tip`, based on the feature tip `e00e991` (LANDED base `5dd8098`, L-174).
Status: NOT GATED. The gate on this tip has not run; no READY-SENIOR exists until it has.

## Why this is not a replay of the sprint 7 package 1 commits

The feature tip already carries a separately written B-064a (`6331c84`, approve, skip, cancel,
headless refusal with exit 3) and the row 6 fix (`8a70840`, Ctrl-C at the approval prompt ends the
step skipped). My package 1 commits implement the same card. Replaying them conflicts in six files
(`src/ract/harness.py` two hunks, `src/ract/harness_report_enricher.py` two hunks,
`src/ract/plan_gate.py`, `src/ract/ract_runner.py`, `tests/test_dead_code_auction.py`,
`tests/test_ract_runner.py`). Choosing one implementation over the other would silently drop
review fixes that the BUILDER landed (L-170 to L-182), so the landed version is the base.

## Commits and hashes (old, from work/s7-b064a, then new on this branch)

| Old (s7-b064a) | New (on this branch) | What |
|---|---|---|
| a799cd3 | 8777938 | raw keys in the pseudo-terminal runner (replayed cleanly) |
| 736082f | fa1bbe8 | package 3: queued notes at the model request (replayed cleanly) |
| 87a3c0c | 70c8878 | fix: the decorator moved to the right function (replayed cleanly) |
| 83f1a9b | 93685d2 | plan gate events registered on the session stream (replayed cleanly) |
| ad7565f, 2027e3e, 0b0f7be (in part), 1ce2f01 | not replayed | superseded by landed 6331c84 and 8a70840 |
| fd53a27 | ported (see below) | approvals persist with the session |

## Ported onto the landed version (new commits, test first)

1. `edit n` (D12). The landed `resolve_answer` answered "edit is not available yet". It now
   returns `Resolution("edit", n=...)`; `apply_edit` (one line, limit 2000 characters, a new path
   must pass the path check) is copied from `ad7565f`; `console_plan_approval` asks for the new text
   and shows the plan again. Conservative choice: the console has no project root, so any path the
   new text names that the plan did not list is refused.
2. Approvals persist with the session (D12). `SessionState.plan_approvals` (default empty),
   `_resumed_approvals`, and `_persisting_approval` wraps the console question in `ract_runner`: a
   plan whose `plan_hash` the session holds is not asked again; a new approval is saved with the
   session. A refusal records nothing. Headless refusal is unchanged (the wrapper only wraps the
   console question).

## Conflicts and resolutions (every hunk; nothing chosen silently)

These are the hunks the replay of `ad7565f` hit. Resolution: keep the landed text and port only
what the landed text lacks.

- `src/ract/plan_gate.py` (add/add): landed kept; `Resolution` gains `n`; `resolve_answer` returns
  `edit`; helpers ported.
- `src/ract/harness.py` (2 hunks): landed kept; my `_report_renumbered` not ported (the landed
  `skipped by you` events come from `6331c84`).
- `src/ract/harness_report_enricher.py` (2 hunks): landed kept (`plan_gate` passthrough is in the
  landed text).
- `src/ract/ract_runner.py` (1 hunk, then the persistence port): landed wiring kept; the wrapper and
  `known_approvals` added.
- `tests/test_dead_code_auction.py` (1 hunk): landed allowlist kept; the `plan_gate.py` entry stays
  removed only if the landed code references it (checked by the gate).
- `tests/test_ract_runner.py` (1 hunk): landed expectations kept.

## Tests written for this branch (NOT RUN; no gate yet)

- `tests/test_plan_edit_at_the_console.py` (6 tests)
- `tests/test_plan_approvals_persist_on_tip.py` (5 tests)
- `tests/test_scripted_answers_match_the_fixture.py` (B-091, 2 tests)
- `tests/test_queued_input_at_model_boundary.py` (10 tests, earlier run: all pass)

## Still open

- Captures at 80, 60 and 40 columns (package 2), the raw-key EOF probe and the interrupt probe
  (package 3), package 4 red team, package 5 gate and journey index.
- B-091: the guide sample `docs/SESSION_GUIDE.md` and `docs/ux/guide/ask_calc_answer.txt` still show
  the old scripted answer; regenerate from a real run before the test that compares them passes.
