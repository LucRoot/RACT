# SWE-bench Lite subset — FakeProvider rerun with ALM engaged

**Date:** 2026-07-26
**Provider:** `fake`
**Corpus:** SWE-bench Lite subset (5 instances)
**ALM gates engaged:** G1..G8 plus sycophancy circuit plus Investigator plus AL-1 attester
**Rerun scope:** mechanism check on FakeProvider (Lateral Chain branch B, ALM module_07). Live-provider reruns are queued as an operator action.

## Result

| Metric | Value |
|---|---|
| passed | 1 |
| failed | 0 |
| skipped | 4 |
| subset_size | 5 |
| pass_rate | 0.20 |

## Notes

- Matches the substrate module_07 baseline (1 of 5); ALM engagement did not change the pass rate on the FakeProvider path.
- Live-provider reruns are the interesting delta; the FakeProvider path is the smoke surface.

RACT 0.4.0
