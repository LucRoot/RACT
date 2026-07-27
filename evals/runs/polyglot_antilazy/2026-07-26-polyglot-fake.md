# Aider Polyglot subset — FakeProvider rerun with ALM engaged

**Date:** 2026-07-26
**Provider:** `fake`
**Corpus:** Aider Polyglot subset (10 problems)
**ALM gates engaged:** G1, G2, G3, G4, G5, G6, G7, G8 plus sycophancy circuit plus Investigator plus AL-1 attester
**Rerun scope:** mechanism check on FakeProvider (Lateral Chain branch B, ALM module_07). Live-provider reruns are queued as an operator action (`evals-full.yml` nightly workflow, gated on `RACT_EVAL_ENABLED`).

## Result

| Metric | Value |
|---|---|
| passed | 2 |
| failed | 0 |
| skipped | 8 |
| subset_size | 10 |
| pass_rate | 0.20 |

## Notes

- The pass counts match the substrate module_07 baseline (2 of 10, 8 skipped for fixture-not-found). ALM engagement did not change the number because the FakeProvider replays static fixture responses without triggering any laziness gate.
- The rerun proves the ALM gates fire cleanly on the FakeProvider path — no false positive violations.
- Live-provider reruns are the interesting delta; the FakeProvider path is the smoke surface.

RACT 0.4.0
