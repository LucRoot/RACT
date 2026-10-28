# Plan approval screen: the shape assumed beside `src/ract/ui/plan_approval_view.py`

Package K, PREPARED and unwired (B-064b waits for B-064a). The BUILDER wires the prompt
and the events. This note states what the module assumes, and where it differs from
ADR-0049 D12 (as recorded in `BOARD/archive/phase-2/GUIDANCE_full_2026-10-23_1022.md`,
review item 2) and from `BOARD/cards/B-064b.md`.

## Assumed event data (D12)

- `plan.approval_requested {plan_hash, steps}`: `plan_hash` is `plan_hash(steps)`, sha256 of the RFC 8785 canonical encoding (`ract.canonical.dumps_jcs`, which the architecture test requires on canonical paths; D12 wrote 'canonical JSON, sorted keys'); `steps`
  is the checklist data (`n`, `action`, `target`).
- `plan.approval_answered {plan_hash, answer, kept, skipped: [{n, reason}], edited}`:
  `answer_record(...)` builds this dictionary. Nothing is emitted here.
- `cancel` ends the turn with the existing `turn.finished` outcome `refused`.

## Differences to decide (the ESCALATE in the log lists them)

1. **Answer words.** The card lists `a`, `s <n>`, `e <n>`, `c`. The parser also accepts
   `approve`, `run`, `yes` (approve), `cancel`, `stop`, `no` (cancel), `skip`, `edit`.
   `no` as cancel is the one a reviewer may not want: it reads as "do not approve" and
   cancels the whole plan. Default: keep it; drop it if the BUILDER prefers.
2. **Confidence on the screen.** The card's example shows `Plan: 3 steps, confidence 0.85`.
   The module prints `Plan: 3 steps` only, because the step data it takes does not carry
   confidence. The BUILDER adds it to the heading when the event carries it.
3. **`skipped` reason text.** D12 says `skipped: [{n, reason}]`; this module writes
   `skipped by the operator`. The reason vocabulary is the BUILDER's.
4. **`kept`.** Assumed to be the list of step numbers that were not skipped.
5. **Edit text.** `parse_answer` reads `e <n>` only. The one line of new text is read by
   the prompt (B-064b, the input helper) and passed to `edit(...)`.
6. **Cancel mapping.** `parse_answer` returns kind `cancel`; mapping it to `refused` is the
   BUILDER's (D12 item iii).

## Not in the module

No input read, no event emitted, no import from the event layer, no approval decision (the
write gate, the secret scan, the tier checks and the trust store are unchanged; D12 item i).
