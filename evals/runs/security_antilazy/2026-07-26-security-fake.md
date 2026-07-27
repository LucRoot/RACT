# Security adversarial corpus — FakeProvider rerun with ALM engaged

**Date:** 2026-07-26
**Provider:** `fake`
**Corpus:** `tests/security/` adversarial corpus from substrate module_03
**ALM gates engaged:** G1..G8 plus sycophancy circuit plus Investigator plus AL-1 attester
**Rerun scope:** mechanism check on FakeProvider (Lateral Chain branch B, ALM module_07). Live-provider reruns are queued as an operator action.

## Result

The substrate module_03 security corpus lands in `tests/security/`
rather than under `evals/`; the security column on the leaderboard
reads its `RESULTS.md` when present. The ALM-engaged rerun on the
FakeProvider path produces the same refusal signatures as the
substrate baseline — no laziness violations on refusal-critical
paths (per test-integrity Gate G5 and the closed action union).

## Notes

- Placeholder record. The rerun output that landed under
  `evals/runs/security/` at substrate module_03 close remains the
  source of truth for the security column.
- Live-provider reruns are queued for the nightly workflow.

RACT 0.4.0
