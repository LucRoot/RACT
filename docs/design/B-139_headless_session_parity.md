# B-139: headless and session parity

Status: first pass, 2026-10-30, BUILDER. Each row is read from the code at the B-137 batch tip (`b2875af`); file and function names are given so a reader can check them.

## One path, three switches

`ract -p` (`headless._run`) and the session (`repl.ReplSession._event_turn`) both build a `session_turn.TurnRequest` and call `session_turn.run_turn`, which calls `ract_runner.run_ract`, which calls the harness. The planner (`Manager.plan`, B-137 included), the step agent loop, the tier gates, the checkpoint, the verifier and the summary are the same code. What differs is what each request carries:

| Field | Session, `default` | Session, `auto-accept` | Session, `plan` | `ract -p` | `ract -p --accept-edits` |
|---|---|---|---|---|---|
| `auto` | true | false | (dry run) | false | false |
| `refuse_changes` | false | false | false | **true** | false |
| `terminal` | true when stdin is a terminal | same | same | false | false |
| `session_id` | the session's | the session's | none (dry run) | none | none |
| `resume` | after the first turn | same | false | false | false |
| `tier3_mode`, approvals | the session's (`/permissions`) | same | n/a | `ask`, none | `ask`, none |
| `token_budget` | `ract.yaml` | same | n/a | `--token-budget` or `ract.yaml` | same |

`run_ract` turns these into the approvers (`ract_runner.py`, the block after the dry-run branch).

## Stage by stage

| Stage | Session `default` | Session `auto-accept` | `ract -p` | `ract -p --accept-edits` | Verdict |
|---|---|---|---|---|---|
| Planning | `Manager.plan` | same | same | same | same code |
| Memory replayed into planning | the session's arena | same | none (`session_id` is none) | none | deliberate: headless is one stateless run |
| Plan approval (ADR-0049 D12, B-137) | asked (`console_plan_approval`, remembered per session) | none | refused when it needs approval (`refuse_plan_needing_approval`) | none | deliberate: nobody to ask means refused, `--accept-edits` is the operator's choice |
| Step approval | asked (`console_approval_callback`) | none | answers only (`refuse_changes_callback`) | none | deliberate; **defect fixed below** |
| Per-hunk review (step loop on) | asked (`console_proposed_reviewer`) | none | n/a (changes refused) | none | deliberate |
| Tier 1 writes | after the step's yes or the review | applied | refused | applied | deliberate |
| Tier 2 calls | asked (`SessionApprovals`) | **refused** (no approver) | refused | refused | **difference inside the session**: see Open below |
| Tier 3 commands | asked at the terminal | asked at the terminal (G-216 W4) | refused (no approver, no terminal) | refused | deliberate: tier 3 needs the operator (ADR-0048 D6) |
| `git init` offer (no repository) | asked | none | none | none | deliberate: an offer needs someone to answer |
| Signing (S-015b) | `provenance_wiring.install` | same | same | same | same code |
| Turn backup and `/undo` | `undo_backup.turn` in `run_turn` | same | same | same | same code |
| Run checkpoint, `--resume` | per session id | same | none | none | deliberate: no session to resume |
| Verification record | `run_turn` | same | same | same | same code |
| Result | the renderer's summary | same | `headless.result_object` (JSON or text), carries `planned` (B-137) | same | same facts, two renderings |

## Defects

1. **`refuse_changes_callback` approved an agent step.** It lets a step run when the step writes no artifact and names no tool call. A B-137 agent step has neither, and it may write any file through the step loop. `ract -p` refuses an agent plan first, at plan approval, but the harness skips plan approval for a replayed plan (`plan_override`). After that, only this callback stands between the agent step and the files. Headless never replays a plan today, so this was not reachable. The callback now refuses an agent step itself; tested in `tests/test_b139_parity.py`.

## Open (a ruling, not a defect by the card's rule)

- **Tier 2 in a session's `auto-accept` mode is refused, where tier 3 asks.** G-216 W4 gave `auto-accept` at a terminal a tier-3 question, but the tier-2 approver is set only in `default`. So a control-file write or a local git write is refused in `auto-accept`, though someone is at the terminal. That path does less, not more, so it is not a permission hole. Either ask there too (the same `SessionApprovals`), or keep it refused and say so in `/permissions`. This is a MANAGER call.

## Tests

`tests/test_b139_parity.py` pins defect 1. The card's two-path tests (the B-137 scenario through `ract -p` and through a session turn, comparing refusals and files changed) are written but not committed: the session-turn half hung in its first run and is being diagnosed.
