# Review index: the lane sprint 6 branches

Every branch below is from the feature tip `081d4a5` (`feat/interactive-session-and-setup-fixes`), built
from `work/ux-more` (tip "[S5] LANDING_KIT: landing tip of sprint 5, 74 commits; whole-tre" at the start of sprint 6). Nothing here is pushed, tagged, released or
rewritten. The BUILDER reviews the senior hunks before any branch lands.

## Landing order

1. `work/hygiene` (tip c573f9f): no senior source change. Tests, README, captures, the dead-code allowlist.
2. `work/B-033s` (tip 7819a97): input owner, type-ahead behind `RACT_TYPE_AHEAD=1`, `/queue`. Senior: `repl.py`, `input_broker.py` (new).
3. `work/H1-H4` (tip f02fa02): false "done" fixes. Senior: `executor/steps.py`, `executor/substrate_adapter.py`, `workspace_path.py`.
4. `work/S6-5` (tip 786a707): handoffs 1, 7, 9, H2, H5, H6. Senior: `executor/steps.py`, `executor/substrate_adapter.py`, `manager.py`, `repl.py`, `session_render.py`, `session_turn.py`, `harness_report_enricher.py`.
5. `work/B-064a` (tip 6fca036): plan approval, first increment. Senior: `session_events.py` (two kinds), `plan_gate.py` (new), `docs/EVENTS_SESSION.md`.

Order note: branches 2 to 5 share files with hygiene and with each other (`repl.py`, `steps.py`). Land them
one at a time and rerun the gate after each.

## Branches

| Order | Branch | Tip | Senior hunks (review file) | Gate (full `tests/`, one run each) |
|---|---|---|---|---|
| 1 | work/hygiene | 6e66047 | none in src; test-policy (BUILDER confirms): `tests/test_dead_code_auction.py` allowlist, `tests/test_modes.py` (wrapped question), `tests/unit/test_intent_recompile_cli.py` (clean exit), `tests/test_egress_ledger.py` (wrapped path); R10 fix in README.md; `tests/ux/run_baseline.py` (RACT_UX_COLS) | 5095 passed, 43 skipped, 1 xfailed, 1 failed (novelty baseline; fails on 081d4a5 too) |
| 2 | work/B-033s | 7819a97 | `repl.py` (type-ahead, `/queue`, queued line, interrupt hook), `input_broker.py` (new); `docs/review/B-033s.md` | 5109 passed, 43 skipped, 1 xfailed, 8 failed |
| 3 | work/H1-H4 | f02fa02 | `steps.py` (hold), `substrate_adapter.py` (wrapper), `workspace_path.py`; `docs/review/H4.md` | 5092 passed, 43 skipped, 1 xfailed, 8 failed (the series list) |
| 4 | work/S6-5 | 786a707 | see `docs/review/H2.md`, `docs/review/H6.md`; `steps.py`, `manager.py`, `repl.py`, `session_render.py`, `session_turn.py`, `harness_report_enricher.py`; test-policy `tests/test_b054f_wording.py` | 5100 passed, 43 skipped, 1 xfailed, 8 failed (the series list) |
| 5 | work/B-064a | 6fca036 | `session_events.py`, `plan_gate.py`, `docs/EVENTS_SESSION.md`; `docs/review/B-064a.md` | 5103 passed, 43 skipped, 1 xfailed, 8 failed (the series list) |

The eight failures on the series branches (B-033s, H1-H4, S6-5, B-064a) are the same list: the novelty detector
(it also fails on the feature tip 081d4a5, so it is not a series regression) and seven that the hygiene branch fixes
(R10, egress ledger, modes x2, closed-IP, intent recompile, dead-code auction). Each series branch shows them because
its base is ux-more, before the hygiene fixes; they disappear when hygiene lands first.

## Each series regression, with the commit that caused it

| Test | Caused by (bisect) | Fixed on | How |
|---|---|---|---|
| R10 README word count | 5547ac1 (UX package E) | 7725f9c | README paragraphs trimmed to 2499 words |
| egress ledger cost | 1198f88 (UX package A) | c573f9f | test compares the path without spaces |
| modes, default asks (2) | d037dbb (UX package H) | "[S6-0] test_modes: the approval question may wrap (d037dbb w" | test pattern allows the wrapped question |
| intent recompile | 2867b10 (UX package S) | 3cd5f72 | test accepts return 0 or SystemExit(0) |
| dead-code auction | 513c9af, 6f44e9f, 2867b10 (J, K, S) | 668b635 | allowlist with reasons (BUILDER confirms) |
| closed-IP wordlist | captures from the terminal matrix and the windows run | 79643f6 | machine-path directory replaced by a placeholder |

The novelty detector (test_executor_routes_low_novelty_to_handshake_queue) fails with `FakeHandshakeRegistry` having no
`project_dir`. It fails on 081d4a5 as well. Handed off to the owner of the handshake test fixture (BUILDER or MANAGER).

## Package states at close (2026-10-27 04:30 PT)

- 0 landing: READY on work/hygiene (6e66047), one named FOUND (the novelty handoff).
- 1 B-033s: READY-SENIOR ce85638 (branch tip 7819a97, tests only). Open: the sprint 4 interim hold (ESCALATE, kept);
  EOF during a turn not probed; a queued line starts a new turn at the prompt, not at the model-request boundary.
- 2 B-064a: PARTIAL at 6fca036. Built and tested: the gate, the answer resolver (approve, skip with dependents, cancel),
  the approval memory, the two event kinds with the D12 fields, the payload builders. Not built: wiring before the first
  step (executor and REPL), edit, the cancel exit mapping, headless exit 3 in a real run, resume wiring, the B-064b
  screen and its captures at 80, 60 and 40 columns. Not READY.
- 3 B-010a, B-011a: BLOCKED (S-028 in review; B-017b todo). Not started.
- 4 H1 and H4: READY-SENIOR f02fa02 (work/H1-H4).
- 5 handoffs: READY-SENIOR 786a707 (work/S6-5). Handoff 2 ESCALATE (headless stdin with an intent; default keeps
  the contract, the xfail stays); H3 ESCALATE (default: a rewrite keeps the BOM).
- 6 red team: PARTIAL. Attacks held: a queued y does not answer an approval; a mode switch while a question is open
  does not answer it; a plan-hash replay does not ask twice; a changed plan asks again. Not attacked: read tools (package 3).
- 7 gate and index: DONE. Gates on every tip above; this index. The gate on 6fca036 is the package 2 gate.
- 8 journeys and look-again: DONE for the journeys (27 captures per width in docs/ux/sprint6), pass 1 (errors row 14,
  ux bar rows 10 and 11, windows page), pass 2 not completed in full; the bar check and Windows page carry the evidence lines.

Landing order: hygiene, B-033s, H1-H4, S6-5, B-064a. Each branch is from 081d4a5 through ux-more; the series
branches show the baseline list until hygiene lands.

## Merged tip (work/integrated, 2026-10-27 10:38 PT)

Built from the feature tip 081d4a5 by merging, in order: hygiene (6e66047 and the index commit 00e3f01),
B-033s (7819a97), H1-H4 (f02fa02), S6-5 (786a707), B-064a (6fca036). Merge commits and fixes after them:
digest relock (56cc606), the dead-code allowlist for plan_gate.py (71ad33d), and the README restore with the new
docs page and the regenerated command table (0cadecd).

- Tip: work/integrated at 0cadecd (README 2422 words, limit 2450).
- Full tests tree, one run, on 56cc606 (the same content as the tip before the last two fixes): 5146 passed,
  43 skipped, 1 xfailed, 2 failed. The two: the novelty detector (also fails on 081d4a5, not a series regression)
  and the dead-code auction flagging plan_gate.py (added in 4111c97, the package 2 decision module, unwired), fixed
  by 71ad33d.
- After the run: tests/docs, tests/test_release_surface.py and tests/test_dead_code_auction.py on 0cadecd: 124
  passed, 1 skipped. The full tree was not run again after the two fixes.
- Conflicts while merging: only src/ract/source_digest.py (resolved by taking the incoming side, then re-locked).
- Landing order for the merged tip: land work/integrated as one branch, or in the same order as the
  branches it replaces (hygiene, B-033s, H1-H4, S6-5, B-064a), since the merged tip contains all five.
